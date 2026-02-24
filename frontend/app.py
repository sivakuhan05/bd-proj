import requests
import streamlit as st

API_BASE_URL = "http://localhost:8000"

st.set_page_config(page_title="Political News Bias Detector", layout="wide")
st.title("📰 Political News Bias Detector")
st.write("Search and manage political news articles stored in MongoDB")


def parse_keywords(raw_keywords: str):
    return [word.strip() for word in raw_keywords.split(",") if word.strip()]


def parse_comments(raw_comments: str):
    comments = []
    if not raw_comments.strip():
        return comments

    for line in raw_comments.splitlines():
        if not line.strip():
            continue
        parts = [part.strip() for part in line.split("|")]
        if len(parts) != 4:
            raise ValueError(
                "Each comment line must follow: user|comment|likes|timestamp"
            )

        user, comment, likes, timestamp = parts
        comments.append(
            {
                "user": user,
                "comment": comment,
                "likes": int(likes),
                "timestamp": timestamp,
            }
        )
    return comments


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
                    author = article.get("author", {})
                    st.write(
                        f"**Author:** {author.get('name', 'N/A')} ({author.get('affiliation', 'N/A')})"
                    )
                    st.write(
                        f"**Published:** {article.get('published_date', 'N/A')} | **Category:** {article.get('category', 'N/A')}"
                    )
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
        author_name = st.text_input("Author Name")
        author_affiliation = st.text_input("Author Affiliation")
        published_date = st.text_input("Published Date (YYYY-MM-DD)")
        category = st.text_input("Category")
        bias_label = st.selectbox("Bias", ["Left", "Right", "Center"], key="create_bias")
        bias_confidence = st.number_input(
            "Bias Confidence", min_value=0.0, max_value=1.0, value=0.5, step=0.01
        )
        content = st.text_area("Content")
        keywords = st.text_input("Keywords (comma-separated)")
        likes = st.number_input("Engagement Likes", min_value=0, value=0, step=1)
        shares = st.number_input("Engagement Shares", min_value=0, value=0, step=1)
        comments_input = st.text_area(
            "Comments (one per line: user|comment|likes|timestamp)",
            help="Example: Alex|Great insights|12|2025-01-10T14:30:00",
        )

        submit_create = st.form_submit_button("Create Article")

    if submit_create:
        try:
            comments = parse_comments(comments_input)
            payload = {
                "title": title,
                "source": source,
                "author": {
                    "name": author_name,
                    "affiliation": author_affiliation,
                },
                "published_date": published_date,
                "category": category,
                "bias": {
                    "label": bias_label,
                    "confidence": float(bias_confidence),
                },
                "content": content,
                "keywords": parse_keywords(keywords),
                "engagement": {
                    "likes": int(likes),
                    "shares": int(shares),
                },
                "comments": comments,
            }

            response = requests.post(f"{API_BASE_URL}/articles", json=payload, timeout=10)
            if response.status_code == 201:
                article = response.json()
                st.success(f"Article created successfully with ID {article['_id']}")
            else:
                st.error(f"Failed to create article: {response.text}")
        except ValueError as error:
            st.error(f"Invalid comments format: {error}")

with update_tab:
    st.subheader("Update Article")

    with st.form("update_article_form"):
        article_id = st.text_input("Article ID to update")
        new_title = st.text_input("New title (optional)")
        new_source = st.text_input("New source (optional)")

        st.markdown("**Author (optional)**")
        new_author_name = st.text_input("New author name (optional)")
        new_author_affiliation = st.text_input("New author affiliation (optional)")

        new_published_date = st.text_input("New published date (optional)")
        new_category = st.text_input("New category (optional)")

        new_bias = st.selectbox("New bias label (optional)", ["", "Left", "Right", "Center"])
        new_bias_confidence = st.text_input("New bias confidence (optional)")

        new_content = st.text_area("New content (optional)")
        new_keywords = st.text_input("New keywords comma-separated (optional)")

        st.markdown("**Engagement (optional)**")
        new_likes = st.text_input("New likes (optional)")
        new_shares = st.text_input("New shares (optional)")

        new_comments = st.text_area(
            "Replace comments (optional, one per line: user|comment|likes|timestamp)"
        )

        submit_update = st.form_submit_button("Update Article")

    if submit_update:
        try:
            payload = {}
            if new_title:
                payload["title"] = new_title
            if new_source:
                payload["source"] = new_source

            author_payload = {}
            if new_author_name:
                author_payload["name"] = new_author_name
            if new_author_affiliation:
                author_payload["affiliation"] = new_author_affiliation
            if author_payload:
                payload["author"] = author_payload

            if new_published_date:
                payload["published_date"] = new_published_date
            if new_category:
                payload["category"] = new_category

            bias_payload = {}
            if new_bias:
                bias_payload["label"] = new_bias
            if new_bias_confidence:
                bias_payload["confidence"] = float(new_bias_confidence)
            if bias_payload:
                payload["bias"] = bias_payload

            if new_content:
                payload["content"] = new_content
            if new_keywords:
                payload["keywords"] = parse_keywords(new_keywords)

            engagement_payload = {}
            if new_likes:
                engagement_payload["likes"] = int(new_likes)
            if new_shares:
                engagement_payload["shares"] = int(new_shares)
            if engagement_payload:
                payload["engagement"] = engagement_payload

            if new_comments:
                payload["comments"] = parse_comments(new_comments)

            response = requests.put(
                f"{API_BASE_URL}/articles/{article_id}", json=payload, timeout=10
            )
            if response.status_code == 200:
                st.success("Article updated successfully")
                st.json(response.json())
            else:
                st.error(f"Failed to update article: {response.text}")
        except ValueError as error:
            st.error(f"Invalid update input: {error}")

with delete_tab:
    st.subheader("Delete Article")

    delete_id = st.text_input("Article ID to delete")
    if st.button("Delete Article", key="btn_delete"):
        response = requests.delete(f"{API_BASE_URL}/articles/{delete_id}", timeout=10)

        if response.status_code == 200:
            st.success(response.json().get("message", "Article deleted"))
        else:
            st.error(f"Failed to delete article: {response.text}")
