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

# --- Data Loading (Definitive Version) ---
@st.cache_data
def load_data():
    """Loads team and player data from JSON files with a direct mapping approach."""
    try:
        with open('chess_team_data.json', 'r', encoding='utf-8') as f:
            team_data = json.load(f)
        with open('chess_player_data.json', 'r', encoding='utf-8') as f:
            player_data = json.load(f)

        # Create clean DataFrames from the dictionary values.
        team_df = pd.DataFrame(team_data.values())
        player_df = pd.DataFrame(player_data.values())

        # --- Build the Link Between Players and Teams ---
        # 1. Create a map of {federation_id: team_name}
        fed_id_to_team = {}
        for _, team_row in team_df.iterrows():
            team_name = team_row['name']
            for fed_id in team_row.get('players', {}).keys():
                fed_id_to_team[fed_id] = team_name

        # 2. Use that map to create the 'team_name' column in the player DataFrame
        def get_team_for_player(player_row):
            # This line is the fix. We use direct bracket access instead of .get()
            # on the pandas Series object (player_row).
            for fed_id in player_row['federation_ids']:
                if fed_id in fed_id_to_team:
                    return fed_id_to_team[fed_id]
            return "Unknown"

        # Apply the function to each row in the player DataFrame
        if not player_df.empty:
            player_df['team_name'] = player_df.apply(get_team_for_player, axis=1)
        else:
            player_df['team_name'] = pd.Series(dtype='str')

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
    # --- Sidebar Filters ---
    st.sidebar.header("Filters")
    federation_filter = st.sidebar.multiselect(
        "Filter by Federation:",
        options=team_df['federation'].unique(),
        default=team_df['federation'].unique()
    )

    # Filter data based on sidebar selection
    filtered_team_df = team_df[team_df['federation'].isin(federation_filter)]

    # --- TEMPORARY DEBUGGING BLOCK ---
    with st.expander("Player Filter Debugging Info"):
        st.write("**1. Teams the filter is looking for:**")
        st.write(filtered_team_df['name'].unique())

        st.write("**2. Team names actually assigned to players:**")
        st.write(player_df['team_name'].unique())

        st.write("**3. Sample of player data with assigned teams:**")
        st.dataframe(player_df[['name', 'team_name', 'total_score']].head(10))
    # --- END DEBUGGING BLOCK ---


    # This is the line that's likely failing
    filtered_player_df = player_df[player_df['team_name'].isin(filtered_team_df['name'])]


    # --- Key Metrics ---
    st.header("🏆 Club Overview")
    col1, col2, col3 = st.columns(3)
    col1.metric("Total Teams", len(filtered_team_df))
    col2.metric("Total Players", len(filtered_player_df)) # This will show 0 if the filter fails
    col3.metric("Total Scraped Matches", sum(len(matches) for _, matches in filtered_team_df['matches'].items() if isinstance(matches, list)))


    # --- Team Analysis Section ---
    st.header("Team Performance")
    st.markdown("### All Team Data")
    # Use the 'name' column for display, which now exists from your fix
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
    # The dataframe being displayed here is the one we are debugging
    st.dataframe(filtered_player_df[['name', 'team_name', 'total_score', 'avg_opponent_rating']].sort_values('name'))

    st.markdown("### Player Score vs. Opposition Strength")
    # Check if the filtered dataframe is not empty before creating a chart
    if not filtered_player_df.empty:
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
    else:
        st.warning("No player data to display based on current filters.")

    # --- Detailed Match View ---
    # This section was already working, but is included for completeness.
    st.header("Detailed Match History")
    if not filtered_team_df.empty:
        selected_team = st.selectbox(
            "Select a team to view its match history:",
            options=filtered_team_df.sort_values('name')['name']
        )
        if selected_team:
            team_with_named_index = filtered_team_df.set_index('name')
            match_history = team_with_named_index.loc[selected_team, 'matches']
            
            if isinstance(match_history, list) and len(match_history) > 0:
                match_df = pd.DataFrame(match_history)
                st.dataframe(match_df[['date', 'opponent', 'location', 'result']])
            else:
                st.warning(f"No match history found or the data is empty for {selected_team}.")
    else:
        st.info("No teams to display based on current filters.")