import streamlit as st
import pandas as pd
import json
import plotly.express as px
import re

# --- Page Configuration ---
st.set_page_config(
    page_title="Chess Club Analytics Dashboard",
    page_icon="♟️",
    layout="wide",
)

# --- Helper Functions ---
def custom_sort_key(team_name):
    """Sorts teams with Arabic numerals before Roman numerals."""
    match = re.search(r'(.+?)\s+([IVXLCDM\d]+)$', team_name)
    if not match: return (2, team_name, 0)
    prefix, number_str = match.groups()
    prefix = prefix.strip()
    if all(c in 'IVXLCDM' for c in number_str.upper()):
        roman_map = {'I': 1, 'V': 5, 'X': 10, 'L': 50, 'C': 100, 'D': 500, 'M': 1000}
        value = 0
        for i in range(len(number_str)):
            if i > 0 and roman_map[number_str[i]] > roman_map[number_str[i-1]]:
                value += roman_map[number_str[i]] - 2 * roman_map[number_str[i-1]]
            else:
                value += roman_map[number_str[i]]
        return (1, prefix, value)
    else:
        try: return (0, prefix, int(number_str))
        except ValueError: return (2, team_name, 0)

# --- UPDATED: Helper function to calculate BP and MP ---
def process_match_history(match_history_list):
    """Takes a list of match dicts and returns a formatted DataFrame with BP and MP."""
    if not isinstance(match_history_list, list) or not match_history_list:
        return pd.DataFrame()

    match_df = pd.DataFrame(match_history_list)
    
    board_points_list = []
    match_points_list = []

    for _, row in match_df.iterrows():
        score_parts = re.split(r'\s*-\s*', row['result'])
        my_score_str = ''
        
        # Determine the team's score string based on location
        if len(score_parts) == 2:
            home_score, away_score = score_parts
            my_score_str = home_score if row['location'] == 'Home' else away_score
        
        # Add the raw Board Points score (e.g., '5½') to our list
        board_points_list.append(my_score_str.strip())

        # Now, calculate Match Points based on the Board Points value
        try:
            # Convert score string (like '5½') to a number for comparison
            bp_value = float(my_score_str.strip().replace('½', '.5'))
            
            # Apply the MP calculation logic
            if bp_value < 4:
                mp_value = 0
            elif bp_value == 4:
                mp_value = 1
            else:  # This covers the case where bp_value > 4
                mp_value = 2
            match_points_list.append(mp_value)
        except (ValueError, AttributeError):
            # If score can't be converted, append N/A
            match_points_list.append('N/A')

    # Add the new columns to the DataFrame
    match_df['Board Points (BP)'] = board_points_list
    match_df['Match Points (MP)'] = match_points_list
    match_df['Round'] = match_df.index + 1

    # Rename and reorder columns for the final display
    display_df = match_df.rename(columns={'date': 'Date', 'opponent': 'Opponent', 'location': 'Location'})
    return display_df[['Round', 'Date', 'Opponent', 'Location', 'Board Points (BP)', 'Match Points (MP)']]

# --- NEW: Helper function to format the match result string ---
def format_result(row):
    """Bolds the score of the selected team based on match location."""
    score_parts = re.split(r'\s*-\s*', row['result'])
    if len(score_parts) == 2:
        home_score, away_score = score_parts
        if row['location'] == 'Home':
            return f"**{home_score}** - {away_score}"
        else:
            return f"{home_score} - **{away_score}**"
    return row['result'] # Fallback if format is unexpected


# --- Data Loading ---
@st.cache_data
def load_data():
    """Loads and links data from JSON files."""
    try:
        with open('chess_team_data.json', 'r', encoding='utf-8') as f:
            team_data = json.load(f)
        with open('chess_player_data.json', 'r', encoding='utf-8') as f:
            player_data = json.load(f)

        team_df = pd.DataFrame(team_data.values())
        player_df = pd.DataFrame(player_data.values())

        fed_id_to_team = {}
        for _, team_row in team_df.iterrows():
            team_name = team_row['name']
            for fed_id in team_row.get('players', {}).keys():
                fed_id_to_team[fed_id] = team_name

        def get_teams_for_player(player_row):
            teams = set()
            for fed_id in player_row['federation_ids']:
                if fed_id in fed_id_to_team:
                    teams.add(fed_id_to_team[fed_id])
            return list(teams) if teams else ["Unknown"]

        if not player_df.empty:
            player_df['teams_played_for'] = player_df.apply(get_teams_for_player, axis=1)
        else:
            player_df['teams_played_for'] = pd.Series(dtype='object')

        return team_df, player_df
    except (FileNotFoundError, json.JSONDecodeError) as e:
        st.error(f"Error loading JSON files: {e}")
        return pd.DataFrame(), pd.DataFrame()

# --- Main App ---
st.title("♟️ Chess Club Analytics Dashboard")
team_df, player_df = load_data()

if team_df.empty or player_df.empty:
    st.warning("Could not load data. Please ensure JSON files are present and correct.")
else:
    # --- Sidebar ---
    st.sidebar.header("Filters")
    federation_filter = st.sidebar.multiselect(
        "Filter by Federation:",
        options=team_df['federation'].unique(),
        default=team_df['federation'].unique()
    )
    filtered_team_df = team_df[team_df['federation'].isin(federation_filter)]
    
    # --- NEW: Round the team ratings right after filtering ---
    if not filtered_team_df.empty:
        filtered_team_df['avg_opponent_rating'] = filtered_team_df['avg_opponent_rating'].round(0).astype(int)

    filtered_team_names = filtered_team_df['name'].unique()
    
    # --- Main layout now uses tabs ---
    tab1, tab2 = st.tabs(["🏆 Club & Team Overview", "👤 Player Deep Dive"])

    with tab1:
        # --- Key Metrics ---
        st.header("Club Overview")
        col1, col2, col3 = st.columns(3)
        col1.metric("Total Teams", len(filtered_team_df))
        # This player count needs to be calculated after the player df is filtered
        # We will calculate it inside the player tab and display it here if needed, or adjust logic.
        # For now, this part is simplified to avoid breaking.
        # col2.metric("Total Players", len(player_df[player_df['teams_played_for'].apply(lambda p_teams: any(t in filtered_team_names for t in p_teams))]))
        col3.metric("Total Scraped Matches", sum(len(matches) for matches in filtered_team_df['matches'] if isinstance(matches, list)))
        
        # --- Team Analysis ---
        st.header("Team Performance")
        
        # --- UPDATED: Renamed columns for display ---
        team_display_df = filtered_team_df.rename(columns={
            'name': 'Team',
            'federation': 'Competition',
            'match_points': 'Match Points (MP)',
            'board_points': 'Board Points (BP)',
            'avg_opponent_rating': 'Avg. Opponent Rating'
        })
        # The rounding is already applied, so this will display whole numbers
        st.dataframe(team_display_df[['Team', 'Competition', 'Match Points (MP)', 'Board Points (BP)', 'Avg. Opponent Rating']].sort_values('Team', key=lambda s: s.map(custom_sort_key)))

        st.markdown("### Team Strength vs. Opposition Strength")
        sorted_legend_names = sorted(filtered_team_names, key=custom_sort_key)
        # The chart will now use the rounded numbers from the y-axis
        fig_teams = px.scatter(
            filtered_team_df, x='match_points', y='avg_opponent_rating', color='name',
            size='board_points', hover_name='name', title='Team Performance: Match Points vs. Average Opponent Rating',
            category_orders={"name": sorted_legend_names}
        )
        st.plotly_chart(fig_teams, use_container_width=True)

        # --- Detailed Match History ---
        st.header("Detailed Match History")
        if not filtered_team_df.empty:
            selected_team = st.selectbox(
                "Select a team to view its match history:",
                options=sorted_legend_names
            )
            if selected_team:
                team_with_named_index = filtered_team_df.set_index('name')
                match_history = team_with_named_index.loc[selected_team, 'matches']
                
                display_df = process_match_history(match_history)
                
                if not display_df.empty:
                    st.dataframe(display_df, use_container_width=True, hide_index=True)
                else:
                    st.warning(f"No match history found for {selected_team}.")

    with tab2:
        # --- Player Deep Dive Tab ---
        st.header("Player Performance")

        filtered_player_df = player_df[
            player_df['teams_played_for'].apply(lambda p_teams: any(t in filtered_team_names for t in p_teams))
        ]

        # --- NEW: Round the player ratings right after filtering ---
        if not filtered_player_df.empty:
            filtered_player_df['avg_opponent_rating'] = filtered_player_df['avg_opponent_rating'].round(0).astype(int)

        # Update the placeholder for the player count in the first tab
        col2.metric("Total Players", len(filtered_player_df))

        # --- UPDATED: Renamed columns for display ---
        player_display_df = filtered_player_df.rename(columns={
            'name': 'Player',
            'teams_played_for': 'Teams',
            'total_score': 'Total Score',
            'avg_opponent_rating': 'Avg. Opponent Rating'
        })
        # This will now display the rounded ratings
        st.dataframe(player_display_df[['Player', 'Teams', 'Total Score', 'Avg. Opponent Rating']].sort_values('Player'))

        st.markdown("### Player Score vs. Opposition Strength")
        if not filtered_player_df.empty:
            exploded_player_df = filtered_player_df.explode('teams_played_for')
            # The chart will now use the rounded numbers for the y-axis
            fig_players = px.scatter(
                exploded_player_df, x='total_score', y='avg_opponent_rating', color='teams_played_for',
                hover_name='name', title='Player Performance: Total Score vs. Average Opponent Rating',
                category_orders={"teams_played_for": sorted_legend_names}
            )
            st.plotly_chart(fig_players, use_container_width=True)