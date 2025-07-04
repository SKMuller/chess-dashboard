import streamlit as st
import pandas as pd
import json
import plotly.express as px
import re

# --- Page Configuration ---
# Use st.set_page_config() as the first Streamlit command
st.set_page_config(
    page_title="Chess Club Analytics Dashboard",
    page_icon="♟️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# --- Helper Functions ---
def custom_sort_key(team_name):
    """
    Creates a sort key to order teams with Arabic numerals (1, 2, 3)
    before teams with Roman numerals (I, II, V).
    """
    match = re.search(r'(.+?)\s+([IVXLCDM\d]+)$', team_name)
    if not match:
        return (2, team_name, 0)

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
        try:
            value = int(number_str)
            return (0, prefix, value)
        except ValueError:
            return (2, team_name, 0)

# --- Data Loading (to handle multiple teams per player) ---
@st.cache_data
def load_data():
    """Loads team and player data, linking players to a list of all teams they played for."""
    try:
        with open('chess_team_data.json', 'r', encoding='utf-8') as f:
            team_data = json.load(f)
        with open('chess_player_data.json', 'r', encoding='utf-8') as f:
            player_data = json.load(f)

        team_df = pd.DataFrame(team_data.values())
        player_df = pd.DataFrame(player_data.values())

        # --- Build the Link Between Players and Teams ---
        fed_id_to_team = {}
        for _, team_row in team_df.iterrows():
            team_name = team_row['name']
            for fed_id in team_row.get('players', {}).keys():
                fed_id_to_team[fed_id] = team_name

        # This function now returns a LIST of all teams found for a player
        def get_teams_for_player(player_row):
            teams = set() # Use a set to automatically handle duplicates
            for fed_id in player_row.get('federation_ids', []):
                if fed_id in fed_id_to_team:
                    teams.add(fed_id_to_team[fed_id])
            # Return a list, or a list with "Unknown" if no teams were found
            return list(teams) if teams else ["Unknown"]

        if not player_df.empty:
            # The new column will be called 'teams_played_for' and will contain lists
            player_df['teams_played_for'] = player_df.apply(get_teams_for_player, axis=1)
        else:
            player_df['teams_played_for'] = pd.Series(dtype='object')

        return team_df, player_df
        
    except (FileNotFoundError, json.JSONDecodeError) as e:
        st.error(f"Error loading or parsing JSON files: {e}")
        return pd.DataFrame(), pd.DataFrame()

# --- Main Dashboard ---
st.title("♟️ Chess Club Analytics Dashboard")
st.markdown("An overview of team and player performance based on scraped data.")

team_df, player_df = load_data()

if team_df is None or player_df is None:
    st.error("Error: JSON files not found. Please make sure `chess_team_data.json` and `chess_player_data.json` are in the same directory as the script.")
else:
    # --- Main Dashboard Body (with legend sorting) ---

    # --- Sidebar Filters ---
    st.sidebar.header("Filters")
    federation_filter = st.sidebar.multiselect(
        "Filter by Federation:",
        options=team_df['federation'].unique(),
        default=team_df['federation'].unique()
    )

    filtered_team_df = team_df[team_df['federation'].isin(federation_filter)]
    filtered_team_names = filtered_team_df['name'].unique()

    filtered_player_df = player_df[
        player_df['teams_played_for'].apply(lambda player_teams: any(team in filtered_team_names for team in player_teams))
    ]

    # --- NEW: Create the sorted list of team names for the legends ---
    sorted_legend_names = sorted(filtered_team_names, key=custom_sort_key)


    # --- Key Metrics ---
    st.header("🏆 Club Overview")
    col1, col2, col3 = st.columns(3)
    col1.metric("Total Teams", len(filtered_team_df))
    col2.metric("Total Players", len(filtered_player_df))
    col3.metric("Total Scraped Matches", sum(len(matches) for matches in filtered_team_df['matches'] if isinstance(matches, list)))


    # --- Team Analysis Section (Updated Chart) ---
    st.header("Team Performance")
    st.markdown("### All Team Data")
    st.dataframe(filtered_team_df[['name', 'federation', 'match_points', 'board_points', 'avg_opponent_rating']].sort_values('name'))

    st.markdown("### Team Strength vs. Opposition Strength")
    fig_teams = px.scatter(
        filtered_team_df,
        x='match_points',
        y='avg_opponent_rating',
        color='name',
        size='board_points',
        hover_name='name',
        title='Team Performance: Match Points vs. Average Opponent Rating',
        # Add this line to enforce the legend order
        category_orders={"name": sorted_legend_names}
    )
    st.plotly_chart(fig_teams, use_container_width=True)


    # --- Player Analysis Section (Updated Chart) ---
    st.header("Player Performance")
    st.markdown("### All Player Data")
    st.dataframe(filtered_player_df[['name', 'teams_played_for', 'total_score', 'avg_opponent_rating']].sort_values('name'))

    st.markdown("### Player Score vs. Opposition Strength")
    if not filtered_player_df.empty:
        exploded_player_df = filtered_player_df.explode('teams_played_for')
        
        fig_players = px.scatter(
            exploded_player_df,
            x='total_score',
            y='avg_opponent_rating',
            color='teams_played_for',
            hover_name='name',
            title='Player Performance: Total Score vs. Average Opponent Rating',
            # Add this line to enforce the legend order
            category_orders={"teams_played_for": sorted_legend_names}
        )
        st.plotly_chart(fig_players, use_container_width=True)
    else:
        st.warning("No player data to display based on current filters.")


    # --- Detailed Match View ---
    st.header("Detailed Match History")
    if not filtered_team_df.empty:
        # Use the sorted list for the selectbox as well
        selected_team = st.selectbox(
            "Select a team to view its match history:",
            options=sorted_legend_names
        )
        if selected_team:
            team_with_named_index = filtered_team_df.set_index('name')
            match_history = team_with_named_index.loc[selected_team, 'matches']
            if isinstance(match_history, list) and len(match_history) > 0:
                match_df = pd.DataFrame(match_history)
                st.dataframe(match_df[['date', 'opponent', 'location', 'result']])
            else:
                st.warning(f"No match history found for {selected_team}.")
    else:
        st.info("No teams to display based on current filters.")