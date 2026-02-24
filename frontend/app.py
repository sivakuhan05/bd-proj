import requests
import streamlit as st

API_BASE_URL = "http://localhost:8000"

st.set_page_config(page_title="Political News Bias Detector", layout="wide")
st.title("📰 Political News Bias Detector")
st.write("Search and manage political news articles stored in MongoDB")


def parse_keywords(raw_keywords: str):
    return [word.strip() for word in raw_keywords.split(",") if word.strip()]


search_tab, create_tab, update_tab, delete_tab = st.tabs(
    ["Read / Query", "Create", "Update", "Delete"]
)

with search_tab:
    st.subheader("Find Articles")

    col1, col2, col3 = st.columns(3)
    with col1:
        bias = st.selectbox("Bias", ["", "Left", "Right", "Center"], key="search_bias")
    with col2:
        source = st.text_input("Source", key="search_source")
    with col3:
        keyword = st.text_input("Keyword", key="search_keyword")

    if st.button("Search Articles", key="btn_search"):
        params = {}
        if bias:
            params["bias"] = bias
        if source:
            params["source"] = source
        if keyword:
            params["keyword"] = keyword

        response = requests.get(f"{API_BASE_URL}/articles", params=params, timeout=10)

        if response.status_code == 200:
            articles = response.json()
            if not articles:
                st.warning("No articles found.")
            else:
                st.success(f"Found {len(articles)} article(s)")
                for article in articles:
                    st.markdown(f"### {article.get('title', 'Untitled')}")
                    st.caption(
                        f"ID: {article.get('_id')} | Source: {article.get('source')} | Bias: {article.get('bias', {}).get('label', 'N/A')}"
                    )
                    if article.get("description"):
                        st.write(f"**Description:** {article['description']}")
                    st.write(article.get("content", ""))
                    st.write(f"**Keywords:** {', '.join(article.get('keywords', []))}")
                    st.markdown("---")
        else:
            st.error(f"Failed to fetch articles: {response.text}")

with create_tab:
    st.subheader("Create Article")

    with st.form("create_article_form"):
        title = st.text_input("Title")
        source = st.text_input("Source")
        bias_label = st.selectbox("Bias", ["Left", "Right", "Center"], key="create_bias")
        description = st.text_area("Description")
        content = st.text_area("Content")
        keywords = st.text_input("Keywords (comma-separated)")

        submit_create = st.form_submit_button("Create Article")

    if submit_create:
        payload = {
            "title": title,
            "source": source,
            "content": content,
            "description": description or None,
            "keywords": parse_keywords(keywords),
            "bias": {"label": bias_label},
        }

        response = requests.post(f"{API_BASE_URL}/articles", json=payload, timeout=10)
        if response.status_code == 201:
            article = response.json()
            st.success(f"Article created successfully with ID {article['_id']}")
        else:
            st.error(f"Failed to create article: {response.text}")

with update_tab:
    st.subheader("Update Article")

    with st.form("update_article_form"):
        article_id = st.text_input("Article ID to update")
        new_title = st.text_input("New title (optional)")
        new_source = st.text_input("New source (optional)")
        new_bias = st.selectbox("New bias (optional)", ["", "Left", "Right", "Center"])
        new_description = st.text_area("New description (optional)")
        new_content = st.text_area("New content (optional)")
        new_keywords = st.text_input("New keywords comma-separated (optional)")

        submit_update = st.form_submit_button("Update Article")

    if submit_update:
        payload = {}
        if new_title:
            payload["title"] = new_title
        if new_source:
            payload["source"] = new_source
        if new_bias:
            payload["bias"] = {"label": new_bias}
        if new_description:
            payload["description"] = new_description
        if new_content:
            payload["content"] = new_content
        if new_keywords:
            payload["keywords"] = parse_keywords(new_keywords)

        response = requests.put(f"{API_BASE_URL}/articles/{article_id}", json=payload, timeout=10)
        if response.status_code == 200:
            st.success("Article updated successfully")
            st.json(response.json())
        else:
            st.error(f"Failed to update article: {response.text}")

with delete_tab:
    st.subheader("Delete Article")

    delete_id = st.text_input("Article ID to delete")
    if st.button("Delete Article", key="btn_delete"):
        response = requests.delete(f"{API_BASE_URL}/articles/{delete_id}", timeout=10)

        if response.status_code == 200:
            st.success(response.json().get("message", "Article deleted"))
        else:
            st.error(f"Failed to delete article: {response.text}")
