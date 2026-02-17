import streamlit as st
import requests

BACKEND_URL = "http://localhost:8000/search"

st.set_page_config(page_title="Political News Bias Detector", layout="wide")

st.title("📰 Political News Bias Detector")
st.write("Query political news articles stored in MongoDB Atlas")

# Sidebar filters
st.sidebar.header("Search Filters")

bias = st.sidebar.selectbox(
    "Bias",
    ["", "Left", "Right", "Center"]
)

source = st.sidebar.text_input("Source (e.g., Fox News, BBC News)")
keyword = st.sidebar.text_input("Keyword")

if st.sidebar.button("Search"):
    params = {}

    if bias:
        params["bias"] = bias
    if source:
        params["source"] = source
    if keyword:
        params["keyword"] = keyword

    response = requests.get(BACKEND_URL, params=params)

    if response.status_code == 200:
        articles = response.json()

        if not articles:
            st.warning("No articles found.")
        else:
            for article in articles:
                st.subheader(article["title"])
                st.caption(f"Source: {article['source']} | Bias: {article['bias']['label']}")
                st.write(article["content"])
                st.markdown("---")
    else:
        st.error("Failed to fetch data from backend")
