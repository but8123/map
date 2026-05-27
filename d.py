import json
import math
import streamlit as st
import folium
from streamlit_folium import st_folium
from streamlit_js_eval import get_geolocation
import osmnx as ox
import networkx as nx

# ─────────────────────────────────────────
# 페이지 설정
# ─────────────────────────────────────────
st.set_page_config(
    page_title="원주 생활 인프라 탐색",
    page_icon="🗺️",
    layout="wide"
)

# ─────────────────────────────────────────
# 상수
# ─────────────────────────────────────────
CATEGORY_MAP = {
    "hospital": "의료",
    "clinic": "의료",

    "townhall": "행정",
    "government": "행정",

    "school": "교육",
    "university": "교육",
    "college": "교육",

    "library": "공공시설",
    "park": "공공시설",
    "sports_centre": "공공시설",

    "police": "안전",
    "fire_station": "안전",
}

COLORS = {
    "의료": "#3b82f6",
    "행정": "#a855f7",
    "교육": "#f97316",
    "공공시설": "#22c55e",
    "안전": "#ef4444",
}

EMOJIS = {
    "의료": "🏥",
    "행정": "🏛️",
    "교육": "🏫",
    "공공시설": "🏟️",
    "안전": "🚒"
}

ALL_CATS = ["의료", "행정", "교육", "공공시설", "안전"]

WALK_SPEED = 80

# ─────────────────────────────────────────
# CSS
# ─────────────────────────────────────────
st.markdown("""
<style>

@import url('https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@400;500;600;700&display=swap');

html, body, [class*="css"] {
    font-family: 'Noto Sans KR', sans-serif;
}

.stApp {
    background: #f5f6fa;
}

#MainMenu, header, footer {
    visibility: hidden;
}

section[data-testid="column"]:first-child > div {
    background: white;
    border-radius: 16px;
    padding: 10px;
}

.section-title {
    font-size: 12px;
    font-weight: 700;
    color: #9ca3af;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    margin: 18px 0 8px 2px;
}

.status-box {
    border-radius: 12px;
    padding: 14px 16px;
    margin: 12px 0;
    font-size: 13px;
    line-height: 1.7;
}

.status-idle {
    background:#f1f5f9;
    color:#64748b;
    border:1px dashed #cbd5e1;
}

.status-pending {
    background:#eff6ff;
    color:#1d4ed8;
    border:1px solid #bfdbfe;
}

.status-done {
    background:#f0fdf4;
    color:#166534;
    border:1px solid #bbf7d0;
}

.rank-card {
    background: white;
    border-radius: 12px;
    padding: 12px 14px;
    margin-bottom: 8px;
    display: flex;
    align-items: center;
    gap: 12px;
    box-shadow: 0 1px 4px rgba(0,0,0,0.07);
    border-left: 4px solid #e5e7eb;
}

.rank-card.r1 { border-left-color: #f59e0b; }
.rank-card.r2 { border-left-color: #94a3b8; }
.rank-card.r3 { border-left-color: #92400e; }

.rank-badge {
    width:28px;
    height:28px;
    border-radius:50%;
    display:flex;
    align-items:center;
    justify-content:center;
    font-size:13px;
    font-weight:700;
    color:white;
    flex-shrink:0;
}

.b1{background:#f59e0b;}
.b2{background:#94a3b8;}
.b3{background:#92400e;}

.rank-name {
    font-size:13px;
    font-weight:700;
    color:#111827;
}

.rank-meta {
    font-size:11px;
    color:#9ca3af;
    margin-top:1px;
}

.rank-right {
    margin-left:auto;
    text-align:right;
}

.rank-dist {
    font-size:16px;
    font-weight:700;
    color:#4361ee;
}

.rank-time {
    font-size:11px;
    color:#9ca3af;
}

div[data-testid="stButton"] > button {
    border-radius: 999px;
    font-weight: 700;
}

@media (max-width: 768px) {

    .block-container {
        padding-left: 0.7rem;
        padding-right: 0.7rem;
        padding-top: 0.8rem;
    }

    .rank-card {
        padding: 10px 11px;
    }

    .rank-dist {
        font-size: 14px;
    }
}

</style>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────
# 유틸 함수
# ─────────────────────────────────────────
def meters_to_time(m):
    mins = max(1, round(m / WALK_SPEED))
    return f"약 {mins}분"


def is_mobile_device():
    try:
        ua = st.context.headers.get("User-Agent", "").lower()
        return "mobile" in ua or "android" in ua or "iphone" in ua
    except Exception:
        return False


def reset_location():
    st.session_state.confirmed_lat = None
    st.session_state.confirmed_lon = None
    st.session_state.pending_lat = None
    st.session_state.pending_lon = None
    st.session_state.results = []


# ─────────────────────────────────────────
# 세션 초기화
# ─────────────────────────────────────────
def init_session():

    defaults = {
        "confirmed_lat": None,
        "confirmed_lon": None,
        "pending_lat": None,
        "pending_lon": None,
        "results": [],
        "active_cats": set(ALL_CATS),
    }

    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


init_session()

# ─────────────────────────────────────────
# 데이터 로딩
# ─────────────────────────────────────────
@st.cache_data
def load_facilities():

    with open("data.geojson", encoding="utf-8") as f:
        geojson = json.load(f)

    result = []

    for feature in geojson["features"]:

        props = feature["properties"]
        geometry = feature["geometry"]

        category = None

        for key in ["amenity", "leisure", "office", "building"]:

            v = props.get(key, "")

            if v in CATEGORY_MAP:
                category = CATEGORY_MAP[v]
                break

        if not category:
            continue

        try:
            t = geometry["type"]

            if t == "Point":
                lon, lat = geometry["coordinates"]

            elif t == "Polygon":
                lon, lat = geometry["coordinates"][0][0]

            elif t == "MultiPolygon":
                lon, lat = geometry["coordinates"][0][0][0]

            else:
                continue

            name = props.get("name")

            if not name:
                continue

            result.append({
                "name": name,
                "category": category,
                "lat": float(lat),
                "lon": float(lon),
            })

        except Exception:
            continue

    return result


@st.cache_resource(show_spinner="🗺️ 도로망 로딩 중…")
def load_graph():

    try:
        return ox.load_graphml("wonju_walk.graphml")

    except Exception:

        G = ox.graph_from_point(
            (37.3334, 127.9300),
            dist=6000,
            network_type="walk",
            simplify=True,
        )

        ox.save_graphml(G, "wonju_walk.graphml")

        return G


# ─────────────────────────────────────────
# 거리 계산
# ─────────────────────────────────────────
def haversine(lat1, lon1, lat2, lon2):

    R = 6371000

    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)

    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2) ** 2
    )

    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def road_shortest_path(G, olat, olon, dlat, dlon):

    try:
        orig = ox.nearest_nodes(G, olon, olat)
        dest = ox.nearest_nodes(G, dlon, dlat)

        nodes = nx.shortest_path(
            G,
            orig,
            dest,
            weight="length"
        )

        coords = [
            (G.nodes[n]["y"], G.nodes[n]["x"])
            for n in nodes
        ]

        dist = 0

        for i in range(len(nodes) - 1):

            edge_data = G.get_edge_data(
                nodes[i],
                nodes[i + 1]
            )

            if edge_data:

                min_edge = min(
                    edge_data.values(),
                    key=lambda x: x.get("length", 0)
                )

                dist += min_edge.get("length", 0)

        return coords, round(dist)

    except Exception:
        return None, None


# ─────────────────────────────────────────
# 카테고리 버튼
# ─────────────────────────────────────────
def render_category_buttons():

    cols = st.columns(2)

    labels = {
        "의료": "🔵 🏥 의료",
        "행정": "🟣 🏛️ 행정",
        "교육": "🟠 🏫 교육",
        "공공시설": "🟢 🏟️ 공공시설",
        "안전": "🔴 🚒 안전",
    }

    for i, cat in enumerate(ALL_CATS):

        with cols[i % 2]:

            active = cat in st.session_state.active_cats

            if active:
                label = labels[cat]
            else:
                label = f"⚪ {EMOJIS[cat]} {cat}"

            if st.button(
                label,
                key=f"cat_btn_{cat}",
                use_container_width=True
            ):

                if cat in st.session_state.active_cats:
                    st.session_state.active_cats.remove(cat)
                else:
                    st.session_state.active_cats.add(cat)

                st.session_state.results = []
                st.rerun()


# ─────────────────────────────────────────
# 메인
# ─────────────────────────────────────────
facilities = load_facilities()

left_col, map_col = st.columns([1, 2.8])

# ─────────────────────────────────────────
# 왼쪽 패널
# ─────────────────────────────────────────
with left_col:

    st.markdown("## 🗺️ 인프라 탐색")

    st.markdown(
        '<div class="section-title">카테고리</div>',
        unsafe_allow_html=True
    )

    render_category_buttons()

    selected_cats = st.session_state.active_cats

    st.markdown(
        '<div class="section-title">탐색 반경</div>',
        unsafe_allow_html=True
    )

    radius = st.slider(
        "반경",
        min_value=300,
        max_value=1500,
        value=800,
        step=100,
        label_visibility="collapsed",
    )

    walk_min = max(1, round(radius / WALK_SPEED))

    st.markdown(
        f"""
        <div style='font-size:13px;color:#6b7280;margin-top:-8px;margin-bottom:4px'>
            <b style='color:#4361ee;font-size:15px'>{radius}m</b>
            &nbsp;·&nbsp; 도보 약 <b>{walk_min}분</b>
        </div>
        """,
        unsafe_allow_html=True
    )

    st.markdown(
        '<div class="section-title">위치</div>',
        unsafe_allow_html=True
    )

    can_select_location = (
        st.session_state.pending_lat is None
        and st.session_state.confirmed_lat is None
    )

    if can_select_location:

        if st.button(
            "📱 현재 내 위치 사용",
            use_container_width=True,
            type="primary"
        ):

            loc = get_geolocation()

            if loc and "coords" in loc:

                st.session_state.pending_lat = round(
                    loc["coords"]["latitude"],
                    6
                )

                st.session_state.pending_lon = round(
                    loc["coords"]["longitude"],
                    6
                )

                st.session_state.results = []

                st.rerun()

            else:
                st.warning(
                    "위치 정보를 가져오지 못했습니다. 브라우저 위치 권한을 허용해주세요."
                )

    else:

        st.button(
            "📱 현재 내 위치 사용",
            use_container_width=True,
            disabled=True
        )

    if st.session_state.pending_lat and not st.session_state.confirmed_lat:

        st.markdown(f"""
        <div class="status-box status-pending">
            🔵 <b>선택한 위치</b><br>
            위도 {st.session_state.pending_lat:.5f}<br>
            경도 {st.session_state.pending_lon:.5f}<br>
            <span style="font-size:12px">
            지도 아래 확정 버튼을 눌러주세요
            </span>
        </div>
        """, unsafe_allow_html=True)

    elif st.session_state.confirmed_lat:

        st.markdown(f"""
        <div class="status-box status-done">
            ✅ <b>확정 위치</b><br>
            위도 {st.session_state.confirmed_lat:.5f}<br>
            경도 {st.session_state.confirmed_lon:.5f}<br>
            <span style="font-size:12px">
            다시 선택하려면 초기화를 눌러주세요
            </span>
        </div>
        """, unsafe_allow_html=True)

    else:

        st.markdown("""
        <div class="status-box status-idle">
            📍 지도를 클릭하거나<br>
            현재 내 위치를 사용하세요
        </div>
        """, unsafe_allow_html=True)

    if st.button("↺ 초기화", use_container_width=True):

        reset_location()

        st.rerun()

# ─────────────────────────────────────────
# 지도
# ─────────────────────────────────────────
with map_col:

    center_lat = (
        st.session_state.confirmed_lat
        or st.session_state.pending_lat
        or 37.3422
    )

    center_lon = (
        st.session_state.confirmed_lon
        or st.session_state.pending_lon
        or 127.9202
    )

    zoom = (
        16
        if st.session_state.confirmed_lat
        or st.session_state.pending_lat
        else 14
    )

    m = folium.Map(
        location=[center_lat, center_lon],
        zoom_start=zoom,
        tiles="CartoDB positron",
    )

    # 시설 마커
    for fac in facilities:

        if fac["category"] not in selected_cats:
            continue

        color = COLORS.get(fac["category"], "#888")

        folium.CircleMarker(
            [fac["lat"], fac["lon"]],
            radius=5,
            color=color,
            fill=True,
            fill_color=color,
            fill_opacity=0.75,
            weight=1.5,
            popup=folium.Popup(
                f"<b>{fac['name']}</b><br>"
                f"{EMOJIS.get(fac['category'], '')} {fac['category']}",
                max_width=180
            ),
        ).add_to(m)
        # 확정 위치가 있을 때 경로 계산 및 표시
    if st.session_state.confirmed_lat:

        clat = st.session_state.confirmed_lat
        clon = st.session_state.confirmed_lon

        folium.Marker(
            [clat, clon],
            popup="✅ 확정 위치",
            icon=folium.Icon(color="red", icon="home", prefix="fa"),
        ).add_to(m)

        folium.Circle(
            [clat, clon],
            radius=radius,
            color="#4361ee",
            weight=1.5,
            fill=True,
            fill_opacity=0.05,
        ).add_to(m)

        if not st.session_state.results:

            with st.spinner("🔍 도로망 기반 최단경로 계산 중…"):

                G = load_graph()
                nearby = []

                for fac in facilities:

                    if fac["category"] not in selected_cats:
                        continue

                    sd = haversine(
                        clat,
                        clon,
                        fac["lat"],
                        fac["lon"]
                    )

                    if sd <= radius:
                        nearby.append({
                            **fac,
                            "straight_dist": round(sd)
                        })

                nearby.sort(key=lambda x: x["straight_dist"])

                results = []

                for fac in nearby[:10]:

                    coords, road_dist = road_shortest_path(
                        G,
                        clat,
                        clon,
                        fac["lat"],
                        fac["lon"]
                    )

                    results.append({
                        **fac,
                        "path_coords": coords,
                        "road_dist": road_dist
                    })

                results.sort(
                    key=lambda x: x["road_dist"] if x["road_dist"] else x["straight_dist"]
                )

                st.session_state.results = results
                st.rerun()

        path_colors = ["#ef4444", "#f97316", "#eab308", "#22c55e", "#3b82f6"]
        label_map = {
            0: "🥇",
            1: "🥈",
            2: "🥉",
            3: "4위",
            4: "5위"
        }

        for i, r in enumerate(st.session_state.results[:5]):

            pc = path_colors[i]
            label = label_map.get(i, "")
            rd = r.get("road_dist")
            time_str = meters_to_time(rd if rd else r["straight_dist"])

            if r.get("path_coords"):

                folium.PolyLine(
                    r["path_coords"],
                    color=pc,
                    weight=6 if i == 0 else 4,
                    opacity=1.0 if i == 0 else 0.65,
                    dash_array=None if i == 0 else "7 5",
                    tooltip=f"{label} {r['name']} · {rd}m · 🚶 {time_str}",
                ).add_to(m)

            fac_color = COLORS.get(r["category"], "#888")
            road_text = f"{rd}m" if rd else "계산 실패"

            folium.CircleMarker(
                [r["lat"], r["lon"]],
                radius=11,
                color=pc,
                fill=True,
                fill_color=fac_color,
                fill_opacity=1,
                weight=3,
                popup=folium.Popup(
                    f"<b>{label} {r['name']}</b><br>"
                    f"{EMOJIS.get(r['category'], '')} {r['category']}<br>"
                    f"🛣️ 도로거리: {road_text}<br>"
                    f"🚶 도보: {time_str}<br>"
                    f"📏 직선: {r['straight_dist']}m",
                    max_width=220
                ),
            ).add_to(m)

    # 확정 전 선택 위치 표시
    elif st.session_state.pending_lat:

        folium.CircleMarker(
            [
                st.session_state.pending_lat,
                st.session_state.pending_lon
            ],
            radius=10,
            color="#4361ee",
            fill=True,
            fill_color="white",
            fill_opacity=1,
            weight=3,
            popup="📍 선택한 위치",
        ).add_to(m)

    map_height = 520 if is_mobile_device() else 680

    map_data = st_folium(
        m,
        width="100%",
        height=map_height,
        returned_objects=["last_clicked"],
        key="main_map",
    )

    # 지도 클릭
    if map_data and map_data.get("last_clicked"):

        clicked = map_data["last_clicked"]

        new_lat = round(clicked["lat"], 6)
        new_lon = round(clicked["lng"], 6)

        can_select_location = (
            st.session_state.pending_lat is None
            and st.session_state.confirmed_lat is None
        )

        if can_select_location:

            st.session_state.pending_lat = new_lat
            st.session_state.pending_lon = new_lon
            st.session_state.results = []

            st.rerun()

    # 위치 확정
    if (
        st.session_state.pending_lat
        and not st.session_state.confirmed_lat
    ):

        st.markdown("### 📍 선택한 위치")

        st.write(
            f"위도 {st.session_state.pending_lat:.5f}, "
            f"경도 {st.session_state.pending_lon:.5f}"
        )

        if st.button(
            "✅ 이 위치로 확정하기",
            use_container_width=True,
            type="primary",
            key="confirm_bottom"
        ):

            st.session_state.confirmed_lat = st.session_state.pending_lat
            st.session_state.confirmed_lon = st.session_state.pending_lon
            st.session_state.results = []

            st.rerun()
        

    
