import streamlit as st
import pandas as pd
import json
import plotly.express as px
import plotly.graph_objects as go
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

        filtered_team_names = filtered_team_df['name'].unique()
        available_players_df = player_df[
            player_df['teams_played_for'].apply(lambda p_teams: any(t in filtered_team_names for t in p_teams))
        ].copy()

        if not available_players_df.empty:
            player_names = sorted(available_players_df['name'].unique())
            selected_player_name = st.selectbox(
                "Select a player to analyze their game history:",
                options=player_names
            )

            if selected_player_name:
                player_info = available_players_df[available_players_df['name'] == selected_player_name].iloc[0]
                games_list = player_info.get('games', [])

                if games_list:
                    game_df = pd.DataFrame(games_list)
                    game_df['game_number'] = range(1, len(game_df) + 1)
                    
                    rating_col = 'elo' if 'elo' in player_info and pd.notna(player_info['elo']) else 'avg_opponent_rating'
                    rating_label = "Player ELO" if rating_col == 'elo' else "Avg. Opponent Rating (Placeholder)"
                    game_df['player_rating'] = player_info[rating_col]
                    
                    # Define a function to map results to marker symbols
                    def get_marker(result, for_player):
                        if result == '1': return 'circle-open' if for_player else 'x'
                        if result == '0': return 'x' if for_player else 'circle-open'
                        return 'diamond' # For draws

                    game_df['player_marker'] = game_df['result'].apply(lambda r: get_marker(r, for_player=True))
                    game_df['opponent_marker'] = game_df['result'].apply(lambda r: get_marker(r, for_player=False))

                    st.markdown(f"### Game-by-Game Chart for {selected_player_name}")
                    if rating_col != 'elo':
                        st.info("ℹ️ **Note:** The 'Player' line on this chart uses the *Average Opponent Rating* as a temporary placeholder.")
                    
                    # --- Create the plot using Plotly Graph Objects for more control ---
                    fig = go.Figure()

                    # Add the Opponent's rating line and markers
                    fig.add_trace(go.Scatter(
                        x=game_df['game_number'], y=game_df['opponent_rating'],
                        mode='lines+markers', name='Opponent Rating',
                        marker_symbol=game_df['opponent_marker'],
                        marker_size=10, marker_color='#EF553B' # Red
                    ))

                    # Add the Player's rating line and markers
                    fig.add_trace(go.Scatter(
                        x=game_df['game_number'], y=game_df['player_rating'],
                        mode='lines+markers', name=f'Player Rating ({rating_label})',
                        marker_symbol=game_df['player_marker'],
                        marker_size=10, marker_color='#636EFA' # Blue
                    ))

                    fig.update_layout(
                        xaxis_title="Game Number",
                        yaxis_title="Rating",
                        legend_title="Entity"
                    )
                    st.plotly_chart(fig, use_container_width=True)

                    # --- Game Results Summary Table ---
                    st.markdown("### Game Results Summary")
                    summary_df = game_df.copy()
                    result_map = {'1': 'Win', '0': 'Loss', '½': 'Draw'}
                    summary_df['Outcome'] = summary_df['result'].map(result_map).fillna('N/A')
                    display_df = summary_df.rename(columns={'round': 'Round', 'player_rating': 'Player ELO', 'opponent_rating': 'Opponent ELO'})
                    st.dataframe(display_df[['Round', 'Player ELO', 'Opponent ELO', 'Outcome']], use_container_width=True, hide_index=True)

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