import requests
from bs4 import BeautifulSoup
import time
import re
import json
from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from webdriver_manager.chrome import ChromeDriverManager
from selenium.common.exceptions import WebDriverException
from concurrent.futures import ThreadPoolExecutor

# --- Configuration ---
# Base URLs for the chess federations
BASE_URLS = {
    "knsb": "https://knsb.netstand.nl",
    "nosbo": "https://nosbo.netstand.nl"
}

# Paths to the main competition pages for each federation
COMPETITION_PATHS = {
    "knsb": "/scores/index/54",
    "nosbo": "/scores/index/16"
}

# --- Data Storage ---
# Dictionaries to hold the scraped data.
# 'all_teams_data' will store details for each club team found.
# 'all_players_data' will store details for each unique player found.
all_teams_data = {}      # Key: full team name (e.g., "SISSA 1"), Value: dict of team data
all_players_data = {}    # Key: player ID (extracted from URL), Value: dict of player data

# --- Helper function for sorting ---
def custom_sort_key(team_name):
    """
    Creates a sort key to order teams with Arabic numerals (1, 2, 3)
    before teams with Roman numerals (I, II, V).
    """
    match = re.search(r'(.+?)\s+([IVXLCDM\d]+)$', team_name)
    if not match:
        return (2, team_name, 0)  # Fallback for names with no number

    prefix, number_str = match.groups()
    prefix = prefix.strip()

    # Handle Roman numerals
    if all(c in 'IVXLCDM' for c in number_str.upper()):
        roman_map = {'I': 1, 'V': 5, 'X': 10, 'L': 50, 'C': 100, 'D': 500, 'M': 1000}
        value = 0
        for i in range(len(number_str)):
            if i > 0 and roman_map[number_str[i]] > roman_map[number_str[i-1]]:
                value += roman_map[number_str[i]] - 2 * roman_map[number_str[i-1]]
            else:
                value += roman_map[number_str[i]]
        return (1, prefix, value)  # Group 1 for Roman numerals
    
    # Handle Arabic numerals
    else:
        try:
            value = int(number_str)
            return (0, prefix, value)  # Group 0 for Arabic numerals
        except ValueError:
            return (2, team_name, 0) # Fallback

# --- Helper Function for HTTP Requests ---
def fetch_page(url, retries=3, delay=2):
    """
    Fetches the content of a given URL using Selenium to render JavaScript.

    Args:
        url (str): The URL to fetch.
        retries (int): Number of retries if the request fails.
        delay (int): Delay in seconds to allow the page to load.

    Returns:
        str: The fully rendered HTML content of the page, or None if fetching fails.
    """
    print(f"Fetching with Selenium: {url}")
    # Set up Chrome options to run in "headless" mode (no visible browser window)
    options = webdriver.ChromeOptions()
    options.add_argument('--headless')
    options.add_argument('--disable-gpu')
    options.add_argument('user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36')


    for i in range(retries):
        try:
            # Use webdriver-manager to automatically handle the browser driver
            driver = webdriver.Chrome(service=ChromeService(ChromeDriverManager().install()), options=options)
            driver.get(url)
            # Wait for the page's JavaScript to load the content
            time.sleep(delay)
            html_content = driver.page_source
            driver.quit() # Close the browser
            
            if html_content:
                return html_content
            else:
                 print(f"Warning: Fetched empty page content for {url}")

        except WebDriverException as e:
            print(f"Error fetching {url} with Selenium (Attempt {i+1}/{retries}): {e}")
            if i < retries - 1:
                print(f"Retrying in {delay * (i+1)} seconds...")
                time.sleep(delay * (i+1))

    print(f"Failed to fetch {url} after {retries} retries.")
    return None

# --- Scraping Logic ---

def scrape_competition_pages(target_prefix):
    """
    Scrapes the main competition pages to find all instances of team names
    and their URLs, allowing for duplicates across different competition phases.

    Returns:
        list: A list of dictionaries, where each dictionary represents a
              team instance found.
              Example: [{'name': 'SISSA 1', 'url': '...', 'domain': 'knsb'}]
    """
    found_teams = []
    team_pattern = re.compile(rf"{re.escape(target_prefix)}\s+([IVXLCDM\d]+)", re.IGNORECASE)

    print(f"Scanning competition pages for teams matching '{target_prefix}...'")
    for domain_key, base_url in BASE_URLS.items():
        comp_url = base_url + COMPETITION_PATHS[domain_key]
        html_content = fetch_page(comp_url)
        if html_content:
            soup = BeautifulSoup(html_content, 'html.parser')
            for a_tag in soup.find_all('a', href=True):
                team_name_text = a_tag.get_text(strip=True)
                if team_pattern.match(team_name_text):
                    relative_path = a_tag['href']
                    full_url = base_url + relative_path
                    found_teams.append({
                        'name': team_name_text,
                        'url': full_url,
                        'domain': domain_key.upper()
                    })
                    print(f"  Found team: {team_name_text} ({domain_key.upper()})")
        else:
            print(f"  Could not fetch competition page for {domain_key}: {comp_url}")
    return found_teams

def _scrape_opponent_rating_from_pairings(pairing_page_html, opponent_team_name, base_url):
    """
    Scrapes a single pairings page to find the average rating of the specified opponent,
    ignoring "ghost" matches where all players are "NN".
    """
    if not pairing_page_html:
        return None

    soup = BeautifulSoup(pairing_page_html, 'html.parser')
    
    results_table = soup.find('table', class_=re.compile(r'table-striped'))
    if not results_table:
        return None

    # --- NEW: Check for "ghost" matches and ignore them ---
    player_links = results_table.find('tbody').find_all('a', href=re.compile(r'/players/view/'))
    if player_links:
        player_names = [link.get_text(strip=True) for link in player_links]
        # If all player names in the list are 'NN', it's a duplicate match to be ignored.
        if all(name == 'NN' for name in player_names):
            print(f"    Ignoring duplicate 'NN' match for opponent {opponent_team_name}.")
            return None # Stop processing this match

    # --- Find which column belongs to the opponent ---
    opponent_col_index = -1
    header_links = results_table.find('thead').find_all('a', href=re.compile(r'/teams/view/'))

    for i, link in enumerate(header_links):
        if link.get_text(strip=True) == opponent_team_name:
            opponent_col_index = i
            break
            
    if opponent_col_index == -1:
        return None

    # --- Find the average rating in the footer using the column index ---
    try:
        footer_rating_labels = results_table.find('tfoot').find_all('th', string=re.compile(r'Gemiddelde Rating:'))
        
        if len(footer_rating_labels) > opponent_col_index:
            rating_cell = footer_rating_labels[opponent_col_index].find_next_sibling('th')
            rating = int(rating_cell.get_text(strip=True))
            return rating
    except (AttributeError, ValueError, IndexError):
        return None
    
    return None

def scrape_team_page(team_instance):
    """
    Scrapes a single instance of a team page.
    This function is designed to be called by the parallel executor.
    """
    team_name = team_instance['name']
    team_url = team_instance['url']
    domain_key_lower = team_instance['domain'].lower() # for URL construction
    federation = team_instance['domain'] # KNSB or NOSBO

    print(f"\nScraping team page for: {team_name} ({federation})")
    html_content = fetch_page(team_url)
    
    # Note: No more global all_teams_data
    team_data = {
        'name': team_name,
        'federation': federation,
        'match_points': 0.0,
        'board_points': 0.0,
        'players': {},
        'matches': [],
        'opponent_ratings_raw': [] # Store raw ratings for aggregation
    }

    if not html_content:
        return team_data # Return empty data on failure

    # ... (The rest of this function's scraping logic is identical to the last version)
    # ... (It finds points, players, and visits pairing pages)
    # The only change is that at the end, it returns the data instead of saving globally.

    soup = BeautifulSoup(html_content, 'html.parser')

    # Part 1: Scrape points and player list
    try:
        point_labels = soup.find_all('b')
        for label in point_labels:
            label_text = label.get_text(strip=True)
            parent_div_text = label.parent.get_text(strip=True)
            if label_text == 'MP':
                score_str = parent_div_text.replace('MP', '').strip().replace(',', '.')
                team_data['match_points'] = float(score_str)
            elif label_text == 'BP':
                score_str = parent_div_text.replace('BP', '').strip().replace(',', '.')
                team_data['board_points'] = float(score_str)
    except (AttributeError, ValueError):
        pass

    player_list_table = soup.find('table', id='DataTables_Table_0')
    if player_list_table:
        for row in player_list_table.find('tbody').find_all('tr'):
            player_link_tag = row.find('a', href=re.compile(r'/players/view/\d+'))
            if player_link_tag:
                player_name = player_link_tag.get_text(strip=True)
                relative_path = player_link_tag['href']
                full_player_url = BASE_URLS[domain_key_lower] + relative_path
                player_id = relative_path.split('/')[-1]
                team_data['players'][player_id] = {'name': player_name, 'url': full_player_url}

    # Part 2: Scrape match list and visit each pairing page
    match_list_table = soup.find('table', class_='table table-striped table-bordered')
    if match_list_table:
        for row in match_list_table.find('tbody').find_all('tr'):
            cells = row.find_all('td')
            if len(cells) != 5:
                continue

            # Try to find the link to the detailed pairings page
            pairing_link_tag = cells[4].find('a')
            
            # Only process rows that have a valid pairings link
            if pairing_link_tag and pairing_link_tag.has_attr('href'):
                base_url = BASE_URLS[domain_key_lower]
                pairing_url = base_url + pairing_link_tag['href']
                
                # Fetch the pairings page and check for a valid rating
                pairing_html = fetch_page(pairing_url)
                home_team = cells[2].get_text(strip=True)
                away_team = cells[3].get_text(strip=True)
                opponent_team_name = away_team if home_team == team_name else home_team
                
                opponent_rating = _scrape_opponent_rating_from_pairings(pairing_html, opponent_team_name, base_url)
                
                # If the rating is valid (not a ghost match), then define and store the match info
                if opponent_rating:
                    print(f"    Found opponent rating for {opponent_team_name}: {opponent_rating}")
                    
                    # Define match_info HERE, only for valid matches
                    match_info = {
                        'date': cells[1].get_text(strip=True),
                        'opponent': opponent_team_name,
                        'location': "Home" if home_team == team_name else "Away",
                        'result': cells[4].get_text(strip=True)
                    }
                    
                    team_data['opponent_ratings_raw'].append(opponent_rating)
                    team_data['matches'].append(match_info)
            
    return team_data

## This function scrapes the player page
def scrape_player_page(player_id, player_url, domain_key):
    """
    Scrapes an individual player page to extract stats and the universal RatingViewer ID.
    """
    print(f"\nScraping player page for federation ID: {player_id} ({player_url})")
    html_content = fetch_page(player_url)

    player_data = {
        'federation_id': player_id,
        'universal_id': None,
        'name': '',
        'total_score': 0.0,
        'opponent_ratings_raw': [],
        'avg_opponent_rating': 0.0
    }

    if not html_content:
        print(f"  No content retrieved for player: {player_id}")
        return player_data

    soup = BeautifulSoup(html_content, 'html.parser')

    # --- Extract Universal RatingViewer ID ---
    try:
        rating_viewer_link = soup.find('a', href=re.compile(r'ratingviewer\.nl/list/latest/players/'))
        if rating_viewer_link:
            href = rating_viewer_link['href']
            # Extract the number from the URL
            universal_id_match = re.search(r'/players/(\d+)/', href)
            if universal_id_match:
                player_data['universal_id'] = universal_id_match.group(1)
    except Exception as e:
        print(f"  Could not find RatingViewer ID for player {player_id}: {e}")

    # --- Extract Player Name ---
    try:
        name_div = soup.find('div', class_='col-lg-4 offset-lg-4 text-center')
        if name_div:
            player_data['name'] = name_div.get_text(strip=True)
    except Exception as e:
        print(f"  Could not extract player name for {player_id}: {e}")

    # --- Extract Game Results from the "Partijen" Table ---
    try:
        games_header = soup.find('span', class_='h3', string='Partijen')
        if games_header:
            card_div = games_header.find_parent('div', class_='card')
            results_table = card_div.find('table')
            
            for row in results_table.find('tbody').find_all('tr'):
                cells = row.find_all('td')
                if not cells or len(cells) < 3: continue

                # Extract Opponent Rating
                opponent_text = cells[1].get_text(strip=True)
                rating_match = re.search(r'\((\d{3,4})\)', opponent_text)
                if rating_match:
                    player_data['opponent_ratings_raw'].append(int(rating_match.group(1)))

                # Extract Player's Score
                score_text = cells[2].get_text(strip=True)
                if score_text == '1':
                    player_data['total_score'] += 1.0
                elif score_text == '½':
                    player_data['total_score'] += 0.5
    except Exception as e:
        print(f"  Could not parse 'Partijen' table for player {player_id}: {e}")
        
    return player_data

## This function runs the scraper and aggregates the data
def run_scraper(target_team_prefix):
    """
    Orchestrates the scraping and aggregation process for both teams and players.
    """
    global all_teams_data, all_players_data
    all_teams_data = {}
    all_players_data = {}

    # --- Team Scraping and Aggregation (Unchanged) ---
    team_instances_to_scrape = scrape_competition_pages(target_team_prefix)
    if not team_instances_to_scrape: return

    print(f"\n--- Scraping {len(team_instances_to_scrape)} team pages in parallel... ---")
    with ThreadPoolExecutor(max_workers=10) as executor:
        team_data_list = list(executor.map(scrape_team_page, team_instances_to_scrape))

    print("\n--- Aggregating team results... ---")
    aggregated_teams_data = {}
    for team_data in team_data_list:
        team_name = team_data['name']
        if team_name not in aggregated_teams_data:
            aggregated_teams_data[team_name] = team_data
        else:
            existing = aggregated_teams_data[team_name]
            existing['matches'].extend(team_data['matches'])
            existing['players'].update(team_data['players'])
            existing['opponent_ratings_raw'].extend(team_data['opponent_ratings_raw'])
            existing['match_points'] = team_data['match_points']
            existing['board_points'] = team_data['board_points']

    for data in aggregated_teams_data.values():
        raw_ratings = data.get('opponent_ratings_raw', [])
        data['avg_opponent_rating'] = sum(raw_ratings) / len(raw_ratings) if raw_ratings else 0.0
    
    all_teams_data = aggregated_teams_data

    # --- Player Scraping and Aggregation (Corrected) ---
    unique_players_to_scrape = {}
    for team_data in all_teams_data.values():
        for player_id, player_info in team_data.get('players', {}).items():
            if player_id not in unique_players_to_scrape:
                domain = 'KNSB' if 'knsb' in player_info['url'] else 'NOSBO'
                unique_players_to_scrape[player_id] = {'url': player_info['url'], 'domain': domain.lower()}

    if unique_players_to_scrape:
        print(f"\n--- Scraping {len(unique_players_to_scrape)} unique player pages in parallel... ---")
        player_scrape_args = [(pid, pinfo['url'], pinfo['domain']) for pid, pinfo in unique_players_to_scrape.items()]
        with ThreadPoolExecutor(max_workers=10) as executor:
            player_data_list = list(executor.map(lambda p: scrape_player_page(*p), player_scrape_args))

    print("\n--- Aggregating player results... ---")
    aggregated_players_data = {}
    for player_data in player_data_list:
        uid = player_data.get('universal_id')
        if not uid: continue

        if uid not in aggregated_players_data:
            # First time seeing this universal ID. Store it and create the federation_ids list.
            player_data['federation_ids'] = [player_data['federation_id']]
            aggregated_players_data[uid] = player_data
        else:
            # We've seen this player before. Merge the data.
            existing = aggregated_players_data[uid]
            existing['total_score'] += player_data['total_score']
            existing['opponent_ratings_raw'].extend(player_data['opponent_ratings_raw'])
            # Add the new federation ID to the list of known IDs for this player.
            existing['federation_ids'].append(player_data['federation_id'])
    
    for data in aggregated_players_data.values():
        raw_ratings = data.get('opponent_ratings_raw', [])
        data['avg_opponent_rating'] = sum(raw_ratings) / len(raw_ratings) if raw_ratings else 0.0
    
    all_players_data = aggregated_players_data
    
    print("\n--- Scraping Complete ---")

    # --- Summaries ---
    print("\n--- Summary of Team Data ---")
    if all_teams_data:
        for team_name in sorted(all_teams_data.keys(), key=custom_sort_key):
            data = all_teams_data[team_name]
            print(f"Team: {team_name} ({data.get('federation', 'N/A')})")
            print(f"  Match Points: {data.get('match_points', 0.0):.1f}")
            print(f"  Board Points: {data.get('board_points', 0.0):.1f}")
            print(f"  Average Opponent Rating: {data.get('avg_opponent_rating', 0.0):.0f}")
            print("-" * 30)
    else:
        print("No team data collected.")

    print("\n--- Summary of Player Data ---")
    if all_players_data:
        sorted_players = sorted(all_players_data.values(), key=lambda x: x.get('name', ''))
        for data in sorted_players:
            print(f"Player: {data.get('name', 'N/A')} (ID: {data.get('universal_id', 'N/A')})")
            print(f"  Total Score: {data.get('total_score', 0.0):.1f}")
            print(f"  Average Opponent Rating: {data.get('avg_opponent_rating', 0.0):.0f}")
            print("-" * 30)
    else:
        print("No player data collected.")
        
    # --- Save to JSON ---
    try:
        with open('chess_team_data.json', 'w', encoding='utf-8') as f:
            json.dump(all_teams_data, f, indent=4, ensure_ascii=False)
        print("\nTeam data saved to 'chess_team_data.json'")

        with open('chess_player_data.json', 'w', encoding='utf-8') as f:
            json.dump(all_players_data, f, indent=4, ensure_ascii=False)
        print("Player data saved to 'chess_player_data.json'")
    except Exception as e:
        print(f"Error saving data to JSON files: {e}")

    # --- Print Summary of Collected Data ---
print("\n--- Summary of Team Data ---")
if all_teams_data:
    for team_name, data in all_teams_data.items():
        print(f"Team: {team_name}")
        # Use the new keys for Match Points and Board Points
        print(f"  Match Points: {data['match_points']:.1f}")
        print(f"  Board Points: {data['board_points']:.1f}")
        print(f"  Average Opponent Rating: {data['avg_opponent_rating']:.0f}")
        print(f"  Players in this team: {[p_info['name'] for p_id, p_info in data['players'].items()]}")
        print("-" * 30)
    else:
        print("No team data collected.")


    print("\n--- Summary of Player Data ---")
    if all_players_data:
        for player_id, data in all_players_data.items():
            print(f"Player: {data['name']} (ID: {player_id})")
            print(f"  Total Season Score: {data['total_score']:.1f}")
            print(f"  Average Opponent Rating: {data['avg_opponent_rating']:.0f}")
            print(f"  Played for teams: {', '.join(data['teams_played_for'].keys())}")
            print("-" * 30)
    else:
        print("No player data collected.")


    # --- Save Data to JSON Files ---
    try:
        with open('chess_team_data.json', 'w', encoding='utf-8') as f:
            json.dump(all_teams_data, f, indent=4, ensure_ascii=False)
        print("\nTeam data saved to 'chess_team_data.json'")

        with open('chess_player_data.json', 'w', encoding='utf-8') as f:
            json.dump(all_players_data, f, indent=4, ensure_ascii=False)
        print("Player data saved to 'chess_player_data.json'")
    except Exception as e:
        print(f"Error saving data to JSON files: {e}")


# --- Main Execution Block ---
if __name__ == "__main__":
    # IMPORTANT: Replace "SISSA" with the actual prefix of your club's team names.
    # For example, if your teams are named "MyClub 1", "MyClub 2", etc., set this to "MyClub".
    CLUB_TEAM_PREFIX = "SISSA" # Placeholder - **CHANGE THIS**

    run_scraper(CLUB_TEAM_PREFIX)
