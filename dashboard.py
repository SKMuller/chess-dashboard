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
            return (0, prefix, int(number_str))
        except ValueError:
            return (2, team_name, 0)

def process_match_history(match_history_list):
    """Takes a list of match dicts and returns a formatted DataFrame with BP and MP."""
    if not isinstance(match_history_list, list) or not match_history_list:
        return pd.DataFrame()
    match_df = pd.DataFrame(match_history_list)
    board_points_list, match_points_list = [], []
    for _, row in match_df.iterrows():
        score_parts = re.split(r'\s*-\s*', row['result'])
        my_score_str = ''
        if len(score_parts) == 2:
            my_score_str = score_parts[0] if row['location'] == 'Home' else score_parts[1]
        board_points_list.append(my_score_str.strip())
        try:
            bp_value = float(my_score_str.strip().replace('½', '.5'))
            if bp_value < 4: mp_value = 0
            elif bp_value == 4: mp_value = 1
            else: mp_value = 2
            match_points_list.append(mp_value)
        except (ValueError, AttributeError):
            match_points_list.append('N/A')
    match_df['Board Points (BP)'] = board_points_list
    match_df['Match Points (MP)'] = match_points_list
    match_df['Round'] = match_df.index + 1
    display_df = match_df.rename(columns={'date': 'Date', 'opponent': 'Opponent', 'location': 'Location'})
    return display_df[['Round', 'Date', 'Opponent', 'Location', 'Board Points (BP)', 'Match Points (MP)']]

# --- Data Loading ---
@st.cache_data
def load_data():
    """Loads and links data from all three JSON files."""
    try:
        with open('chess_team_data.json', 'r', encoding='utf-8') as f: team_data = json.load(f)
        with open('chess_player_data.json', 'r', encoding='utf-8') as f: player_data = json.load(f)
        with open('chess_division_data.json', 'r', encoding='utf-8') as f: division_data = json.load(f)
        team_df = pd.DataFrame(team_data.values())
        player_df = pd.DataFrame(player_data.values())
        division_df = pd.DataFrame(division_data.values())
        if not team_df.empty:
            fed_id_to_team = {fed_id: team_row['name'] for _, team_row in team_df.iterrows() for fed_id in team_row.get('players', {}).keys()}
            def get_teams_for_player(player_row):
                teams = {fed_id_to_team[fed_id] for fed_id in player_row.get('federation_ids', []) if fed_id in fed_id_to_team}
                return list(teams) if teams else ["Unknown"]
            if not player_df.empty:
                player_df['teams_played_for'] = player_df.apply(get_teams_for_player, axis=1)
        return team_df, player_df, division_df
    except (FileNotFoundError, json.JSONDecodeError) as e:
        st.error(f"Error loading JSON files: {e}")
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

# --- Main App ---
st.title("♟️ Chess Club Analytics Dashboard")
team_df, player_df, division_df = load_data()

if team_df.empty:
    st.warning("Could not load data. Please ensure JSON files are present and correct.")
else:
    # --- Sidebar ---
    st.sidebar.header("Filters")
    all_team_names = sorted(team_df['name'].unique(), key=custom_sort_key)
    default_teams = [name for name in all_team_names if name.startswith("SISSA")]
    selected_teams = st.sidebar.multiselect("Select Teams to Display:", options=all_team_names, default=default_teams)
    
    filtered_team_df = team_df[team_df['name'].isin(selected_teams)].copy()
    if not filtered_team_df.empty:
        filtered_team_df['avg_opponent_rating'] = filtered_team_df['avg_opponent_rating'].fillna(0).round(0).astype(int)

    # --- Main layout with three tabs ---
    tab1, tab2, tab3 = st.tabs(["🏆 Club & Team Overview", "👤 Player Deep Dive", "⚔️ Division Analytics"])


    with tab1:
        # Code for Tab 1
        filtered_team_names_tab1 = filtered_team_df['name'].unique()
        filtered_player_df_tab1 = player_df[player_df['teams_played_for'].apply(lambda p_teams: any(t in filtered_team_names_tab1 for t in p_teams))]
        st.header("Club Overview")
        col1, col2, col3 = st.columns(3)
        col1.metric("Total Teams Shown", len(filtered_team_df))
        col2.metric("Total Players Shown", len(filtered_player_df_tab1))
        col3.metric("Total Scraped Matches", sum(len(matches) for matches in filtered_team_df['matches'] if isinstance(matches, list)))
        st.header("Team Performance")
        team_display_df = filtered_team_df.rename(columns={'name': 'Team', 'federation': 'Competition', 'match_points': 'Match Points (MP)', 'board_points': 'Board Points (BP)', 'avg_opponent_rating': 'Avg. Opponent Rating'})
        st.dataframe(team_display_df[['Team', 'Competition', 'Match Points (MP)', 'Board Points (BP)', 'Avg. Opponent Rating']].sort_values('Team', key=lambda s: s.map(custom_sort_key)))
        st.markdown("### Team Strength vs. Opposition Strength")
        sorted_legend_names_tab1 = sorted(filtered_team_df['name'].unique(), key=custom_sort_key)
        fig_teams = px.scatter(filtered_team_df, x='match_points', y='avg_opponent_rating', color='name', size='board_points', hover_name='name', title='Team Performance: Match Points vs. Average Opponent Rating', category_orders={"name": sorted_legend_names_tab1})
        st.plotly_chart(fig_teams, use_container_width=True)
        st.header("Detailed Match History")
        if not filtered_team_df.empty:
            selected_team_tab1 = st.selectbox("Select a team to view its match history:", options=sorted_legend_names_tab1, key="team_selector_tab1")
            if selected_team_tab1:
                team_with_named_index = filtered_team_df.set_index('name')
                match_history = team_with_named_index.loc[selected_team_tab1, 'matches']
                display_df = process_match_history(match_history)
                if not display_df.empty: st.dataframe(display_df, use_container_width=True, hide_index=True)
                else: st.warning(f"No match history found for {selected_team_tab1}.")

    with tab2:
        st.header("Player Deep Dive")

        # Filter players based on the teams selected in the sidebar
        filtered_team_names = filtered_team_df['name'].unique()
        available_players_df = player_df[
            player_df['teams_played_for'].apply(lambda p_teams: any(t in filtered_team_names for t in p_teams))
        ].copy()

        if not available_players_df.empty:
            # Dropdown to select a single player
            player_names = sorted(available_players_df['name'].unique())
            selected_player_name = st.selectbox(
                "Select a player to analyze their game history:",
                options=player_names
            )

            if selected_player_name:
                # Get the selected player's data
                player_info = available_players_df[available_players_df['name'] == selected_player_name].iloc[0]
                games_list = player_info.get('games', [])

                if games_list:
                    # --- Prepare data for the plot ---
                    game_df = pd.DataFrame(games_list)
                    game_df['game_number'] = range(1, len(game_df) + 1)
                    
                    # Use placeholder rating for the player
                    player_rating_placeholder = player_info['avg_opponent_rating']
                    game_df['player_rating_temp'] = player_rating_placeholder
                    
                    # Create a "long format" DataFrame suitable for Plotly Express
                    plot_data = []
                    for _, game in game_df.iterrows():
                        # Determine markers: 'O' for win, 'X' for loss
                        player_marker = 'circle' # Default for draw
                        opponent_marker = 'circle'
                        if game['result'] == '1':
                            player_marker = 'circle-open'
                            opponent_marker = 'x'
                        elif game['result'] == '0':
                            player_marker = 'x'
                            opponent_marker = 'circle-open'
                        
                        # Add a row for the player's rating point
                        plot_data.append([game['game_number'], game['player_rating_temp'], 'Player', player_marker])
                        # Add a row for the opponent's rating point
                        plot_data.append([game['game_number'], game['opponent_rating'], 'Opponent', opponent_marker])
                    
                    plot_df = pd.DataFrame(plot_data, columns=['Game Number', 'Rating', 'Entity', 'Marker'])

                    # --- Add the disclaimer and create the plot ---
                    st.info("ℹ️ **Note:** The 'Player' line on this chart uses the *Average Opponent Rating* as a temporary placeholder for the player's actual rating.")
                    
                    fig = px.line(
                        plot_df,
                        x='Game Number',
                        y='Rating',
                        color='Entity', # Creates the two separate lines
                        symbol='Marker', # Uses our 'O' and 'X' markers
                        title=f"Game-by-Game Rating Chart for {selected_player_name}",
                        markers=True # Ensures markers are visible
                    )
                    # Customize marker symbols
                    fig.update_traces(marker_size=10, selector=dict(mode='markers'))
                    st.plotly_chart(fig, use_container_width=True)
                else:
                    st.warning(f"No game-by-game data available for {selected_player_name}.")
        else:
            st.info("No players to display based on current filters.")


    with tab3:
        st.header("Division Analytics")
        if division_df.empty:
            st.warning("`chess_division_data.json` not found or empty.")
        else:
            selected_division_name = st.selectbox("Select a division to analyze:", options=division_df['name'].unique())
            if selected_division_name:
                division_info = division_df[division_df['name'] == selected_division_name].iloc[0]
                division_teams = [team['name'] for team in division_info.get('teams', {}).values()]
                
                plot_df_exploded = player_df.explode('teams_played_for')
                plot_df = plot_df_exploded[plot_df_exploded['teams_played_for'].isin(division_teams)]

                if not plot_df.empty:
                    st.markdown("### Player Rating Distribution (Box Plot)")
                    sorted_division_teams = sorted(plot_df['teams_played_for'].unique(), key=custom_sort_key)
                    
                    # Determine which rating to use (elo or placeholder)
                    rating_col = 'elo' if 'elo' in plot_df.columns and not plot_df['elo'].isnull().all() else 'avg_opponent_rating'
                    rating_label = "Player ELO Rating" if rating_col == 'elo' else "Avg. Opponent Rating (Placeholder)"
                    if rating_col != 'elo':
                        st.info("ℹ️ **Note:** Using *Average Opponent Rating* as a substitute for player ELO. Re-run the scraper to get actual ELO data.")

                    fig_box = px.box(
                        plot_df, x="teams_played_for", y=rating_col, color="teams_played_for",
                        title=f"Rating Distribution in {selected_division_name}",
                        labels={"teams_played_for": "Team", rating_col: rating_label},
                        category_orders={"teams_played_for": sorted_division_teams}
                    )
                    st.plotly_chart(fig_box, use_container_width=True)

                    # --- NEW: Line plot for comparing team strength depth ---
                    st.markdown("### Team Strength Comparison (Line Plot)")

                    line_plot_teams = st.multiselect(
                        "Select teams to compare in the line plot:",
                        options=sorted_division_teams,
                        default=sorted_division_teams
                    )

                    if line_plot_teams:
                        line_plot_df = plot_df[plot_df['teams_played_for'].isin(line_plot_teams)].copy()
                        
                        # Sort players by rating within each team and assign a rank
                        line_plot_df.sort_values(by=rating_col, ascending=False, inplace=True)
                        line_plot_df['player_rank'] = line_plot_df.groupby('teams_played_for').cumcount() + 1
                        
                        fig_line = px.line(
                            line_plot_df,
                            x='player_rank',
                            y=rating_col,
                            color='teams_played_for',
                            markers=True,
                            hover_name='name',
                            title='Team Rating Depth Comparison',
                            labels={
                                "player_rank": "Player Strength Rank (Highest to Lowest)",
                                rating_col: rating_label
                            }
                        )
                        st.plotly_chart(fig_line, use_container_width=True)

                else:
                    st.warning("No player rating data found for the teams in this division.")