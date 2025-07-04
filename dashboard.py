import streamlit as st
import pandas as pd
import json
import plotly.express as px

# --- Page Configuration ---
# Use st.set_page_config() as the first Streamlit command
st.set_page_config(
    page_title="Chess Club Analytics Dashboard",
    page_icon="♟️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# --- Data Loading ---
# Use a cache decorator to load data only once
@st.cache_data
def load_data():
    """Loads team and player data from JSON files."""
    try:
        with open('chess_team_data.json', 'r', encoding='utf-8') as f:
            team_data = json.load(f)
        with open('chess_player_data.json', 'r', encoding='utf-8') as f:
            player_data = json.load(f)
        
        # Convert dictionaries to pandas DataFrames
        team_df = pd.DataFrame.from_dict(team_data, orient='index')
        player_df = pd.DataFrame.from_dict(player_data, orient='index')

        # Add team name to player_df for easier filtering later
        player_to_team = {}
        for team_name, data in team_data.items():
            for player_id in data.get('players', {}):
                # This finds the universal_id for a given federation_id
                for uid, pdata in player_data.items():
                    if player_id in pdata.get('federation_ids', []):
                         player_to_team[uid] = team_name
                         break

        player_df['team_name'] = player_df.index.map(player_to_team)


        return team_df, player_df
    except FileNotFoundError:
        return None, None

# --- Main Dashboard ---
st.title("♟️ Chess Club Analytics Dashboard")
st.markdown("An overview of team and player performance based on scraped data.")

team_df, player_df = load_data()

if team_df is None or player_df is None:
    st.error("Error: JSON files not found. Please make sure `chess_team_data.json` and `chess_player_data.json` are in the same directory as the script.")
else:
    # --- Sidebar Filters ---
    st.sidebar.header("Filters")
    # Filter by Federation
    federation_filter = st.sidebar.multiselect(
        "Filter by Federation:",
        options=team_df['federation'].unique(),
        default=team_df['federation'].unique()
    )
    
    # Filter data based on sidebar selection
    filtered_team_df = team_df[team_df['federation'].isin(federation_filter)]
    filtered_player_df = player_df[player_df['team_name'].isin(filtered_team_df['name'])]


    # --- Key Metrics ---
    st.header("🏆 Club Overview")
    col1, col2, col3 = st.columns(3)
    col1.metric("Total Teams", len(filtered_team_df))
    col2.metric("Total Players", len(filtered_player_df))
    col3.metric("Total Scraped Matches", sum(len(matches) for matches in filtered_team_df['matches']))


    # --- Team Analysis Section ---
    st.header("Team Performance")
    
    st.markdown("### All Team Data")
    st.dataframe(filtered_team_df[['name', 'federation', 'match_points', 'board_points', 'avg_opponent_rating']].sort_values('name'))

    st.markdown("### Team Strength vs. Opposition Strength")
    fig_teams = px.scatter(
        filtered_team_df,
        x='match_points',
        y='avg_opponent_rating',
        color='federation',
        size='board_points',
        hover_name='name',
        title='Team Performance: Match Points vs. Average Opponent Rating'
    )
    st.plotly_chart(fig_teams, use_container_width=True)


    # --- Player Analysis Section ---
    st.header("Player Performance")
    
    st.markdown("### All Player Data")
    st.dataframe(filtered_player_df[['name', 'team_name', 'total_score', 'avg_opponent_rating']].sort_values('name'))

    st.markdown("### Player Score vs. Opposition Strength")
    fig_players = px.scatter(
        filtered_player_df,
        x='total_score',
        y='avg_opponent_rating',
        color='team_name',
        size='total_score',
        hover_name='name',
        title='Player Performance: Total Score vs. Average Opponent Rating'
    )
    st.plotly_chart(fig_players, use_container_width=True)


    # --- Detailed Match View ---
    st.header("Detailed Match History")
    selected_team = st.selectbox(
        "Select a team to view its match history:",
        options=filtered_team_df.sort_values('name')['name']
    )
    if selected_team:
        match_history = filtered_team_df.loc[selected_team, 'matches']
        if match_history:
            match_df = pd.DataFrame(match_history)
            st.dataframe(match_df[['date', 'opponent', 'location', 'result']])
        else:
            st.write(f"No match history available for {selected_team}.")