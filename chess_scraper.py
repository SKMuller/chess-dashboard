import requests
from bs4 import BeautifulSoup
import time
import re
import json
from concurrent.futures import ThreadPoolExecutor

# --- Selenium and WebDriver Imports ---
from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService
from webdriver_manager.chrome import ChromeDriverManager
from selenium.common.exceptions import WebDriverException, TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# --- Configuration ---
BASE_URLS = {
    "knsb": "https://knsb.netstand.nl",
    "nosbo": "https://nosbo.netstand.nl"
}

COMPETITION_PATHS = {
    "knsb": "/scores/index/54",
    "nosbo": "/scores/index/16"
}

# --- Data Storage ---
all_teams_data = {}
all_players_data = {}
all_divisions_data = {}

# --- Helper Functions ---
def fetch_page(url, retries=5, delay=30):
    print(f"Fetching with Selenium: {url}")
    options = webdriver.ChromeOptions()
    options.add_argument('--headless')
    options.add_argument('--disable-gpu')
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument('user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36')

    for i in range(retries):
        try:
            # --- THIS IS THE DEFINITIVE FIX ---
            # Changed DriverManager() to ChromeDriverManager() to match the import
            driver = webdriver.Chrome(service=ChromeService(ChromeDriverManager().install()), options=options)
            
            driver.get(url)
            
            WebDriverWait(driver, delay).until(
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )
            
            try:
                iframe = WebDriverWait(driver, 3).until(
                    EC.presence_of_element_located((By.TAG_NAME, "iframe"))
                )
                print(f"  Iframe found, switching context...")
                driver.switch_to.frame(iframe)
                WebDriverWait(driver, delay).until(
                    EC.presence_of_element_located((By.TAG_NAME, "body"))
                )
            except TimeoutException:
                pass
            
            html_content = driver.page_source
            driver.quit()
            
            if html_content:
                return html_content
        except (WebDriverException, TimeoutException) as e:
            print(f"  Error fetching {url} (Attempt {i+1}/{retries}): {e}")
            if i < retries - 1:
                wait_time = (i + 1) * 5 
                print(f"  Retrying in {wait_time} seconds...")
                time.sleep(wait_time)
            else:
                print(f"  Giving up on {url} after {retries} attempts.")

    print(f"Failed to fetch {url} after all retries.")
    return None

def _scrape_opponent_rating_from_pairings(pairing_page_html, opponent_team_name, base_url):
    if not pairing_page_html: return None
    soup = BeautifulSoup(pairing_page_html, 'html.parser')
    results_table = soup.find('table', class_=re.compile(r'table-striped'))
    if not results_table: return None
    player_links = results_table.find('tbody').find_all('a', href=re.compile(r'/players/view/'))
    if player_links and all(link.get_text(strip=True) == 'NN' for link in player_links):
        return None
    opponent_col_index = -1
    header_links = results_table.find('thead').find_all('a', href=re.compile(r'/teams/view/'))
    for i, link in enumerate(header_links):
        if link.get_text(strip=True) == opponent_team_name:
            opponent_col_index = i
            break
    if opponent_col_index == -1: return None
    try:
        footer_rating_labels = results_table.find('tfoot').find_all('th', string=re.compile(r'Gemiddelde Rating:'))
        if len(footer_rating_labels) > opponent_col_index:
            rating_cell = footer_rating_labels[opponent_col_index].find_next_sibling('th')
            return int(rating_cell.get_text(strip=True))
    except (AttributeError, ValueError, IndexError): return None
    return None

# --- Scraping Logic ---
def scrape_competition_pages(target_prefix):
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
                    full_url = base_url + a_tag['href']
                    found_teams.append({'name': team_name_text, 'url': full_url, 'domain': domain_key.upper()})
                    print(f"  Found team: {team_name_text} ({domain_key.upper()})")
    return found_teams

def scrape_team_page(team_instance):
    team_name = team_instance['name']
    team_url = team_instance['url']
    domain_key_lower = team_instance['domain'].lower()
    federation = team_instance['domain']

    print(f"\nScraping team page for: {team_name} ({federation})")
    html_content = fetch_page(team_url)
    
    team_data = {
        'name': team_name, 'federation': federation, 'division_url': None,
        'match_points': 0.0, 'board_points': 0.0, 'players': {},
        'matches': [], 'opponent_ratings_raw': []
    }

    if not html_content:
        return team_data

    soup = BeautifulSoup(html_content, 'html.parser')

    division_link = soup.find('a', href=re.compile(r'/divisions/view/'))
    if division_link: team_data['division_url'] = BASE_URLS[domain_key_lower] + division_link['href']

    try:
        point_labels = soup.find_all('b')
        for label in point_labels:
            label_text = label.get_text(strip=True)
            parent_div_text = label.parent.get_text(strip=True)
            if label_text == 'MP': team_data['match_points'] = float(parent_div_text.replace('MP', '', 1).strip().replace(',', '.'))
            elif label_text == 'BP': team_data['board_points'] = float(parent_div_text.replace('BP', '', 1).strip().replace(',', '.'))
    except (AttributeError, ValueError): pass

    player_list_table = soup.find('table', id='DataTables_Table_0')
    if player_list_table:
        for row in player_list_table.find('tbody').find_all('tr'):
            player_link_tag = row.find('a', href=re.compile(r'/players/view/\d+'))
            if player_link_tag:
                player_id = player_link_tag['href'].split('/')[-1]
                full_player_url = BASE_URLS[domain_key_lower] + player_link_tag['href']
                team_data['players'][player_id] = {'name': player_link_tag.get_text(strip=True), 'url': full_player_url}

    match_list_table = soup.find('table', class_='table table-striped table-bordered')
    if match_list_table:
        for row in match_list_table.find('tbody').find_all('tr'):
            cells = row.find_all('td')
            if len(cells) != 5: continue
            pairing_link_tag = cells[4].find('a')
            if pairing_link_tag and pairing_link_tag.has_attr('href'):
                home_team = cells[2].get_text(strip=True)
                away_team = cells[3].get_text(strip=True)
                opponent_team_name = away_team if home_team == team_name else home_team
                base_url = BASE_URLS[domain_key_lower]
                pairing_html = fetch_page(base_url + pairing_link_tag['href'])
                opponent_rating = _scrape_opponent_rating_from_pairings(pairing_html, opponent_team_name, base_url)
                if opponent_rating:
                    team_data['opponent_ratings_raw'].append(opponent_rating)
                    team_data['matches'].append({'date': cells[1].get_text(strip=True),'opponent': opponent_team_name,'location': "Home" if home_team == team_name else "Away",'result': cells[4].get_text(strip=True)})
    return team_data

def scrape_division_page(division_url, domain_key):
    print(f"\nScraping division page: {division_url}")
    html_content = fetch_page(division_url)
    division_data = {'name': '', 'federation': domain_key.upper(), 'teams': {}, 'players': {}}
    if not html_content: return division_data
    soup = BeautifulSoup(html_content, 'html.parser')
    header = soup.find('h1')
    if header: division_data['name'] = header.get_text(strip=True)
    teams_header = soup.find('h2', string='Teams')
    if teams_header:
        teams_table = teams_header.find_next('table')
        if teams_table:
            for row in teams_table.find('tbody').find_all('tr'):
                link = row.find('a', href=re.compile(r'/teams/view/'))
                if link:
                    division_data['teams'][link['href'].split('/')[-1]] = {'name': link.get_text(strip=True)}
    players_table = soup.find('table', class_='dataTable')
    if players_table:
        for row in players_table.find('tbody').find_all('tr'):
            link = row.find('a', href=re.compile(r'/players/view/'))
            if link:
                division_data['players'][link['href'].split('/')[-1]] = {'name': link.get_text(strip=True)}
    return division_data

def scrape_player_page(player_id, player_url, domain_key):
    """
    Scrapes a player page for all available stats, including a detailed
    list of individual games played.
    """
    print(f"\nScraping player page for federation ID: {player_id} ({player_url})")
    html_content = fetch_page(player_url)

    player_data = {
        'federation_id': player_id,
        'universal_id': None,
        'name': '',
        'elo': None,
        # Overall stats from 'Statistieken' table
        'tpr': None,
        'w_we': None,
        'games_played': 0,
        'wins': 0,
        'draws': 0,
        'losses': 0,
        'color_balance': None,
        'color_distribution': '',
        # --- NEW: Key for detailed game-by-game results ---
        'games': [],
        # Aggregated stats from the 'Partijen' table (we'll still calculate these)
        'total_score': 0.0,
        'opponent_ratings_raw': [],
        'avg_opponent_rating': 0.0,
    }

    if not html_content:
        return player_data

    soup = BeautifulSoup(html_content, 'html.parser')

    # Part 1: Scrape Name, Universal ID, and ELO Rating
    try:
        player_data['name'] = soup.find('div', class_='col-lg-4 offset-lg-4 text-center').get_text(strip=True)
        rating_viewer_link = soup.find('a', href=re.compile(r'ratingviewer\.nl/list/latest/players/'))
        if rating_viewer_link:
            player_data['universal_id'] = re.search(r'/players/(\d+)/', rating_viewer_link['href']).group(1)
        rating_label = soup.find('b', string='Rating')
        if rating_label:
            rating_str = rating_label.parent.get_text(strip=True).replace('Rating', '').strip()
            player_data['elo'] = int(rating_str)
    except Exception:
        pass

    # Part 2: Scrape the "Statistieken" table
    try:
        stats_header = soup.find('span', class_='h3', string='Statistieken')
        if stats_header:
            stats_table = stats_header.find_parent('div', class_='card').find('table')
            stats_map = {cells[0].get_text(strip=True): cells[1].get_text(strip=True) for row in stats_table.find('tbody').find_all('tr') if len(cells := row.find_all('td')) == 2}
            player_data.update({
                'tpr': int(stats_map.get('TPR')) if stats_map.get('TPR') else None,
                'w_we': float(stats_map.get('W-We')) if stats_map.get('W-We') else None,
                'games_played': int(stats_map.get('Gespeeld')) if stats_map.get('Gespeeld') else 0,
                'wins': int(stats_map.get('Gewonnen')) if stats_map.get('Gewonnen') else 0,
                'draws': int(stats_map.get('Remise')) if stats_map.get('Remise') else 0,
                'losses': int(stats_map.get('Verloren')) if stats_map.get('Verloren') else 0,
                'color_balance': int(stats_map.get('Kleursaldo')) if stats_map.get('Kleursaldo') else None
            })
            color_cell_row = stats_table.find('td', string='Kleurverdeling')
            if color_cell_row and (color_cell := color_cell_row.find_next_sibling('td')):
                player_data['color_distribution'] = "".join(['b' if 'fas' in i['class'] else 'w' for i in color_cell.find_all('i')])
    except Exception as e:
        print(f"  Could not parse statistics table for player {player_id}: {e}")

    # --- Part 3: Scrape the "Partijen" table for detailed game data ---
    try:
        games_header = soup.find('span', class_='h3', string='Partijen')
        if games_header:
            results_table = games_header.find_parent('div', class_='card').find('table')
            for row in results_table.find('tbody').find_all('tr'):
                cells = row.find_all('td')
                if not cells or len(cells) < 3: continue

                # Extract data from each cell in the row
                round_info = cells[0].get_text(strip=True)
                opponent_text = cells[1].get_text(strip=True)
                result_text = cells[2].get_text(strip=True)
                color = cells[3].get_text(strip=True) if len(cells) > 3 else 'N/A'
                
                opponent_name = opponent_text.split('(')[0].strip()
                rating_match = re.search(r'\((\d{3,4})\)', opponent_text)
                opponent_rating = int(rating_match.group(1)) if rating_match else None

                # Create a dictionary for this single game
                game_data = {
                    "round": round_info,
                    "opponent_name": opponent_name,
                    "opponent_rating": opponent_rating,
                    "result": result_text,
                    "color": color
                }
                player_data['games'].append(game_data)

                # Still update the aggregate stats for backward compatibility
                if opponent_rating:
                    player_data['opponent_ratings_raw'].append(opponent_rating)
                if result_text == '1':
                    player_data['total_score'] += 1.0
                elif result_text == '½':
                    player_data['total_score'] += 0.5
    except Exception as e:
        print(f"  Could not parse games table for player {player_id}: {e}")

    # Calculate final average opponent rating
    if player_data['opponent_ratings_raw']:
        player_data['avg_opponent_rating'] = sum(player_data['opponent_ratings_raw']) / len(player_data['opponent_ratings_raw'])

    return player_data

def update_empty_teams(target_team_prefix):
    """
    Loads existing team data, finds teams with empty records,
    and re-scrapes only those specific teams.
    """
    print("--- RUNNING IN UPDATE MODE ---")
    
    # --- Step 1: Load the existing data file ---
    try:
        with open('chess_team_data.json', 'r', encoding='utf-8') as f:
            current_team_data = json.load(f)
        print("Successfully loaded 'chess_team_data.json'.")
    except (FileNotFoundError, json.JSONDecodeError):
        print("Could not find or read 'chess_team_data.json'. Please run a full scrape first.")
        return

    # --- Step 2: Identify the names of teams that need updating ---
    empty_team_names = set()
    for team_name, data in current_team_data.items():
        # A failed scrape is identified by having no players and no matches
        if not data.get('players') and not data.get('matches'):
            empty_team_names.add(team_name)

    if not empty_team_names:
        print("No empty teams found to update. All data is complete.")
        return

    print(f"Found {len(empty_team_names)} empty teams to update: {', '.join(empty_team_names)}")

    # --- Step 3: Find the URLs for the empty teams ---
    print("Finding current URLs for empty teams...")
    all_teams_on_site = scrape_competition_pages(target_team_prefix)
    
    teams_to_update = [
        team for team in all_teams_on_site 
        if team['name'] in empty_team_names
    ]

    if not teams_to_update:
        print("Could not find the empty teams on the competition pages. They may have been removed.")
        return

    # --- Step 4: Re-scrape only the necessary teams ---
    print(f"--- Re-scraping {len(teams_to_update)} failed team pages... ---")
    with ThreadPoolExecutor(max_workers=15) as executor:
        updated_team_data_list = list(executor.map(scrape_team_page, teams_to_update))

    # --- Step 5: Update the main data object and save the file ---
    updates_made = 0
    for new_data in updated_team_data_list:
        team_name = new_data['name']
        # Check if the new scrape was successful before updating
        if new_data.get('players') or new_data.get('matches'):
            current_team_data[team_name] = new_data
            updates_made += 1
            print(f"  Successfully updated data for {team_name}.")
        else:
            print(f"  Failed to update data for {team_name} on this attempt.")

    if updates_made > 0:
        try:
            with open('chess_team_data.json', 'w', encoding='utf-8') as f:
                json.dump(current_team_data, f, indent=4, ensure_ascii=False)
            print(f"\nSuccessfully updated {updates_made} team(s) in 'chess_team_data.json'.")
        except Exception as e:
            print(f"Error saving updated data to JSON file: {e}")
    else:
        print("\nNo teams were successfully updated on this run.")

def run_scraper(target_team_prefix):
    global all_teams_data, all_players_data, all_divisions_data
    all_teams_data, all_players_data, all_divisions_data = {}, {}, {}
    print(f"--- Discovering divisions containing '{target_team_prefix}' teams... ---")
    sissa_teams_to_find = scrape_competition_pages(target_team_prefix)
    if not sissa_teams_to_find:
        print(f"No teams with prefix '{target_team_prefix}' found. Cannot proceed.")
        return
    unique_division_urls, cached_team_data = {}, {}
    with ThreadPoolExecutor(max_workers=50) as executor:
        sissa_team_data_list = list(executor.map(scrape_team_page, sissa_teams_to_find))
    for team_data in sissa_team_data_list:
        cached_team_data[team_data['name']] = team_data
        div_url = team_data.get('division_url')
        if div_url: unique_division_urls[div_url] = 'knsb' if 'knsb' in div_url else 'nosbo'
    if not unique_division_urls:
        print("Could not find any division pages to scrape.")
        return
    print(f"\n--- Scraping {len(unique_division_urls)} unique division pages... ---")
    all_teams_to_scrape, all_players_in_divisions = {}, {}
    with ThreadPoolExecutor(max_workers=50) as executor:
        division_results = list(executor.map(lambda p: scrape_division_page(p[0], p[1]), unique_division_urls.items()))
    for res in division_results:
        if res.get('name'):
            all_divisions_data[res['name']] = res
            domain, base_url = res['federation'], BASE_URLS[res['federation'].lower()]
            for team_id, team_info in res.get('teams', {}).items():
                if team_id not in all_teams_to_scrape: all_teams_to_scrape[team_id] = {**team_info, 'url': f"{base_url}/teams/view/{team_id}", 'domain': domain}
            for player_id, player_info in res.get('players', {}).items():
                if player_id not in all_players_in_divisions: all_players_in_divisions[player_id] = {**player_info, 'url': f"{base_url}/players/view/{player_id}", 'domain': domain}
    teams_to_scrape_now = [t for t in all_teams_to_scrape.values() if t['name'] not in cached_team_data]
    team_instances = [{'name': t['name'], 'url': t['url'], 'domain': t['domain']} for t in teams_to_scrape_now]
    print(f"\n--- Scraping {len(team_instances)} remaining team pages in parallel... ---")
    with ThreadPoolExecutor(max_workers=50) as executor:
        newly_scraped_team_data = list(executor.map(scrape_team_page, team_instances))
    final_team_data_list = list(cached_team_data.values()) + newly_scraped_team_data
    print("\n--- Aggregating all team results... ---")
    aggregated_teams_data = {}
    for team_data in final_team_data_list:
        team_name = team_data['name']
        if team_name not in aggregated_teams_data: aggregated_teams_data[team_name] = team_data
        else:
            existing = aggregated_teams_data[team_name]
            existing['matches'].extend(team_data['matches']); existing['players'].update(team_data['players']); existing['opponent_ratings_raw'].extend(team_data['opponent_ratings_raw'])
    for data in aggregated_teams_data.values():
        raw_ratings = data.get('opponent_ratings_raw', [])
        data['avg_opponent_rating'] = sum(raw_ratings) / len(raw_ratings) if raw_ratings else 0.0
    all_teams_data = aggregated_teams_data
    unique_players_to_scrape = all_players_in_divisions
    for team_data in all_teams_data.values():
        for player_id, player_info in team_data.get('players', {}).items():
            if player_id not in unique_players_to_scrape:
                unique_players_to_scrape[player_id] = {'url': player_info['url'], 'domain': 'KNSB' if 'knsb' in player_info['url'] else 'NOSBO'}
    if unique_players_to_scrape:
        print(f"\n--- Scraping {len(unique_players_to_scrape)} unique player pages in parallel... ---")
        player_scrape_args = [(pid, pinfo['url'], pinfo.get('domain', 'knsb').lower()) for pid, pinfo in unique_players_to_scrape.items()]
        with ThreadPoolExecutor(max_workers=50) as executor:
            player_data_list = list(executor.map(lambda p: scrape_player_page(*p), player_scrape_args))
        print("\n--- Aggregating player results... ---")
        aggregated_players_data = {}
        for player_data in player_data_list:
            uid = player_data.get('universal_id')
            if not uid: continue
            if uid not in aggregated_players_data:
                player_data['federation_ids'] = [player_data['federation_id']]
                aggregated_players_data[uid] = player_data
            else:
                existing = aggregated_players_data[uid]
                existing['total_score'] += player_data.get('total_score', 0.0)
                existing['opponent_ratings_raw'].extend(player_data.get('opponent_ratings_raw', []))
                existing['federation_ids'].append(player_data['federation_id'])
        for data in aggregated_players_data.values():
            raw_ratings = data.get('opponent_ratings_raw', [])
            data['avg_opponent_rating'] = sum(raw_ratings) / len(raw_ratings) if raw_ratings else 0.0
        all_players_data = aggregated_players_data
    print("\n--- Scraping Complete ---")
    try:
        with open('chess_team_data.json', 'w', encoding='utf-8') as f: json.dump(all_teams_data, f, indent=4, ensure_ascii=False)
        print("\nTeam data saved to 'chess_team_data.json'")
        with open('chess_division_data.json', 'w', encoding='utf-8') as f: json.dump(all_divisions_data, f, indent=4, ensure_ascii=False)
        print("Division data saved to 'chess_division_data.json'")
        with open('chess_player_data.json', 'w', encoding='utf-8') as f: json.dump(all_players_data, f, indent=4, ensure_ascii=False)
        print("Player data saved to 'chess_player_data.json'")
    except Exception as e: print(f"Error saving data to JSON files: {e}")

# --- Debugging and Main Execution ---
def debug_multiple_teams():
    print("--- RUNNING IN MULTI-TEAM DEBUG MODE ---")
    teams_to_debug = [
        {'name': 'SISSA 1', 'url': 'https://knsb.netstand.nl/teams/view/5415', 'domain': 'KNSB'},
        {'name': 'SISSA 2', 'url': 'https://knsb.netstand.nl/teams/view/5407', 'domain': 'KNSB'}
    ]
    for team_instance in teams_to_debug:
        result = scrape_team_page(team_instance)
        print(f"\n--- FINAL DATA FOR {team_instance['name']} ---")
        print(json.dumps(result, indent=4))

if __name__ == "__main__":
    CLUB_TEAM_PREFIX = "SISSA"
    
    # --- To run the new UPDATE mode ---
    update_empty_teams(CLUB_TEAM_PREFIX)
    
    # --- To run a FULL scrape (comment out the line above) ---
    # print("--- STARTING FULL SCRAPE ---")
    # start_time = time.monotonic()
    # run_scraper(CLUB_TEAM_PREFIX)
    # end_time = time.monotonic()
    # duration = end_time - start_time
    # print("-" * 40)
    # print(f"Total script execution time: {duration:.2f} seconds")
    # print("-" * 40)