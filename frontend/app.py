import requests
import streamlit as st

API_BASE_URL = "http://localhost:8000"

st.set_page_config(page_title="Political News Bias App", layout="wide")
st.title("Political News Bias App")
st.write("Upload, classify, search, and delete articles stored in MongoDB.")


def parse_csv_list(raw_value: str):
    return [word.strip() for word in raw_value.split(",") if word.strip()]


def parse_topic_scores(raw_value: str):
    result = {}
    if not raw_value.strip():
        return result

    for item in raw_value.split(","):
        token = item.strip()
        if not token:
            continue
        if ":" not in token:
            raise ValueError("Topic scores must be comma-separated key:value pairs.")
        key, value = token.split(":", 1)
        result[key.strip()] = float(value.strip())
    return result


def parse_comments(raw_comments: str):
    comments = []
    if not raw_comments.strip():
        return comments

    for line in raw_comments.splitlines():
        token = line.strip()
        if not token:
            continue

        parts = [part.strip() for part in token.split("|")]
        if len(parts) not in (4, 5):
            raise ValueError(
                "Each comment line must be user|comment|likes|timestamp or include optional |flag1,flag2."
            )

        flags = parse_csv_list(parts[4]) if len(parts) == 5 else []
        comments.append(
            {
                "user": parts[0],
                "comment": parts[1],
                "likes": int(parts[2]),
                "timestamp": parts[3],
                "flags": flags,
            }
        )
    return comments


def parse_optional_int(raw_value: str, field_name: str):
    token = raw_value.strip()
    if not token:
        return None
    try:
        return int(token)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be an integer.") from exc


def parse_optional_float(raw_value: str, field_name: str):
    token = raw_value.strip()
    if not token:
        return None
    try:
        return float(token)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be a number.") from exc


def render_article_card(article):
    author = article.get("author") or {}
    publisher = article.get("publisher") or {}
    classification = article.get("classification") or {}

    st.markdown(f"### {article.get('title', 'Untitled')}")
    st.caption(f"ID: {article.get('_id', '')}")
    st.write(
        f"Author: {author.get('name', 'N/A')} | Publisher: {publisher.get('name', 'N/A')}"
    )
    st.write(
        f"Bias: {classification.get('label', 'N/A')} | Confidence: {classification.get('confidence', 'N/A')}"
    )
    st.write(
        f"Published: {article.get('published_date', 'N/A')} | Category: {article.get('category', 'N/A')}"
    )
    st.write(f"Keywords: {', '.join(article.get('keywords', []))}")
    st.write(article.get("content", ""))
    st.markdown("---")


upload_tab, search_tab, update_tab, delete_tab = st.tabs(
    ["Upload + Classify", "Search", "Update", "Delete"]
)

with upload_tab:
    st.subheader("Upload Article")
    st.caption("Manual text upload only.")

    with st.form("upload_article_form"):
        title = st.text_input("Title")
        published_date = st.text_input("Published Date (YYYY-MM-DD)")
        category = st.text_input("Category")

        col1, col2 = st.columns(2)
        with col1:
            author_name = st.text_input("Author Name")
            author_affiliation = st.text_input("Author Affiliation")
            author_aliases = st.text_input("Author Aliases (comma-separated)")
        with col2:
            publisher_name = st.text_input("Publisher Name")
            publisher_website = st.text_input("Publisher Website")
            publisher_country = st.text_input("Publisher Country")
            publisher_aliases = st.text_input("Publisher Aliases (comma-separated)")

        content_manual = st.text_area("Article Content")

        st.markdown("#### Classification")
        class_col1, class_col2, class_col3 = st.columns(3)
        with class_col1:
            bias_label = st.selectbox("Label", ["Left", "Right", "Center"])
        with class_col2:
            bias_confidence = st.number_input(
                "Confidence",
                min_value=0.0,
                max_value=1.0,
                value=0.5,
                step=0.01,
            )
        with class_col3:
            model_version = st.text_input("Model Version", value="prototype-v1")

        st.markdown("#### Search + Enrichment")
        keywords = st.text_input("Keywords (comma-separated)")
        topic_scores_input = st.text_input(
            "Topic Scores (topic:score,topic:score)",
            help="Example: economy:0.8,health:0.1",
        )

        st.markdown("#### Engagement + Comments")
        eng_col1, eng_col2, eng_col3 = st.columns(3)
        with eng_col1:
            likes = st.number_input("Likes", min_value=0, value=0, step=1)
        with eng_col2:
            shares = st.number_input("Shares", min_value=0, value=0, step=1)
        with eng_col3:
            views = st.number_input("Views", min_value=0, value=0, step=1)
        comments_input = st.text_area(
            "Comments (one per line)",
            help="Format: user|comment|likes|timestamp|flag1,flag2 (flags optional)",
        )

        submit_upload = st.form_submit_button("Upload Article")

    if submit_upload:
        try:
            final_content = content_manual
            if not final_content.strip():
                st.error("Article content is required.")
            elif not author_name.strip():
                st.error("Author name is required.")
            elif not publisher_name.strip():
                st.error("Publisher name is required.")
            else:
                payload = {
                    "title": title,
                    "content": final_content,
                    "published_date": published_date or None,
                    "category": category or None,
                    "author": {
                        "name": author_name,
                        "affiliation": author_affiliation or None,
                        "aliases": parse_csv_list(author_aliases),
                    },
                    "publisher": {
                        "name": publisher_name,
                        "website": publisher_website or None,
                        "country": publisher_country or None,
                        "aliases": parse_csv_list(publisher_aliases),
                    },
                    "classification": {
                        "label": bias_label,
                        "confidence": float(bias_confidence),
                        "model_version": model_version or "prototype-v1",
                    },
                    "keywords": parse_csv_list(keywords),
                    "engagement": {
                        "likes": int(likes),
                        "shares": int(shares),
                        "views": int(views),
                    },
                    "comments": parse_comments(comments_input),
                    "topic_scores": parse_topic_scores(topic_scores_input),
                }

                response = requests.post(f"{API_BASE_URL}/articles", json=payload, timeout=15)
                if response.status_code == 201:
                    st.success("Article uploaded successfully.")
                else:
                    st.error(f"Upload failed: {response.text}")
        except ValueError as error:
            st.error(f"Invalid input: {error}")

with search_tab:
    st.subheader("Search Articles")

    row1_col1, row1_col2, row1_col3 = st.columns(3)
    with row1_col1:
        q = st.text_input("Full-text Query", help="Search in title/content.")
    with row1_col2:
        author = st.text_input("Author")
    with row1_col3:
        publisher = st.text_input("Publisher")

    row2_col1, row2_col2, row2_col3, row2_col4, row2_col5 = st.columns(5)
    with row2_col1:
        keyword = st.text_input("Keywords (comma-separated)")
    with row2_col2:
        category = st.text_input("Category")
    with row2_col3:
        bias = st.selectbox("Bias", ["", "Left", "Right", "Center"], key="search_bias")
    with row2_col4:
        limit = st.number_input("Limit", min_value=1, max_value=200, value=50, step=1)
    with row2_col5:
        skip = st.number_input("Skip", min_value=0, value=0, step=1)

    if st.button("Search", key="btn_search"):
        params = {"limit": int(limit), "skip": int(skip)}
        if q:
            params["q"] = q
        if author:
            params["author"] = author
        if publisher:
            params["publisher"] = publisher
        if keyword:
            params["keyword"] = keyword
        if category:
            params["category"] = category
        if bias:
            params["bias"] = bias

        response = requests.get(f"{API_BASE_URL}/articles", params=params, timeout=15)
        if response.status_code == 200:
            articles = response.json()
            if not articles:
                st.warning("No articles found.")
            else:
                st.success(f"Found {len(articles)} article(s)")
                for article in articles:
                    render_article_card(article)
        else:
            st.error(f"Search failed: {response.text}")

with update_tab:
    st.subheader("Update Existing Article")

    with st.form("update_article_form"):
        article_id = st.text_input("Article ID (required)")

        st.markdown("#### Basic Fields (optional)")
        upd_title = st.text_input("Title")
        upd_content = st.text_area("Article Content")
        upd_published_date = st.text_input("Published Date (YYYY-MM-DD)")
        upd_category = st.text_input("Category")

        st.markdown("#### Author (optional)")
        upd_author_name = st.text_input("Author Name")
        upd_author_affiliation = st.text_input("Author Affiliation")
        upd_author_aliases = st.text_input("Author Aliases (comma-separated)")

        st.markdown("#### Publisher (optional)")
        upd_publisher_name = st.text_input("Publisher Name")
        upd_publisher_website = st.text_input("Publisher Website")
        upd_publisher_country = st.text_input("Publisher Country")
        upd_publisher_aliases = st.text_input("Publisher Aliases (comma-separated)")

        st.markdown("#### Classification (optional)")
        upd_bias_label = st.selectbox("Label", ["", "Left", "Right", "Center"], key="upd_bias")
        upd_bias_confidence = st.text_input("Confidence (0.0 - 1.0)")
        upd_model_version = st.text_input("Model Version")

        st.markdown("#### Keywords / Topic Scores (optional)")
        upd_keywords = st.text_input("Keywords (comma-separated)")
        upd_topic_scores = st.text_input(
            "Topic Scores (topic:score,topic:score)",
            help="Example: economy:0.8,health:0.1",
        )

        st.markdown("#### Engagement (optional)")
        upd_likes = st.text_input("Likes")
        upd_shares = st.text_input("Shares")
        upd_views = st.text_input("Views")

        upd_comments = st.text_area(
            "Replace Comments (one per line)",
            help="Format: user|comment|likes|timestamp|flag1,flag2 (flags optional)",
        )

        submit_update = st.form_submit_button("Update Article")

    if submit_update:
        try:
            if not article_id.strip():
                st.error("Article ID is required.")
            else:
                payload = {}

                if upd_title.strip():
                    payload["title"] = upd_title.strip()
                if upd_content.strip():
                    payload["content"] = upd_content.strip()
                if upd_published_date.strip():
                    payload["published_date"] = upd_published_date.strip()
                if upd_category.strip():
                    payload["category"] = upd_category.strip()

                author_requested = any(
                    [
                        upd_author_name.strip(),
                        upd_author_affiliation.strip(),
                        upd_author_aliases.strip(),
                    ]
                )
                if author_requested:
                    if not upd_author_name.strip():
                        st.error("Author Name is required when updating author details.")
                        payload = None
                    else:
                        author_payload = {"name": upd_author_name.strip()}
                        if upd_author_affiliation.strip():
                            author_payload["affiliation"] = upd_author_affiliation.strip()
                        if upd_author_aliases.strip():
                            author_payload["aliases"] = parse_csv_list(upd_author_aliases)
                        payload["author"] = author_payload

                if payload is not None:
                    publisher_requested = any(
                        [
                            upd_publisher_name.strip(),
                            upd_publisher_website.strip(),
                            upd_publisher_country.strip(),
                            upd_publisher_aliases.strip(),
                        ]
                    )
                    if publisher_requested:
                        if not upd_publisher_name.strip():
                            st.error("Publisher Name is required when updating publisher details.")
                            payload = None
                        else:
                            publisher_payload = {"name": upd_publisher_name.strip()}
                            if upd_publisher_website.strip():
                                publisher_payload["website"] = upd_publisher_website.strip()
                            if upd_publisher_country.strip():
                                publisher_payload["country"] = upd_publisher_country.strip()
                            if upd_publisher_aliases.strip():
                                publisher_payload["aliases"] = parse_csv_list(upd_publisher_aliases)
                            payload["publisher"] = publisher_payload

                if payload is not None:
                    classification_payload = {}
                    if upd_bias_label:
                        classification_payload["label"] = upd_bias_label
                    conf_value = parse_optional_float(upd_bias_confidence, "Confidence")
                    if conf_value is not None:
                        if conf_value < 0.0 or conf_value > 1.0:
                            raise ValueError("Confidence must be between 0.0 and 1.0.")
                        classification_payload["confidence"] = conf_value
                    if upd_model_version.strip():
                        classification_payload["model_version"] = upd_model_version.strip()
                    if classification_payload:
                        payload["classification"] = classification_payload

                    if upd_keywords.strip():
                        payload["keywords"] = parse_csv_list(upd_keywords)
                    if upd_topic_scores.strip():
                        payload["topic_scores"] = parse_topic_scores(upd_topic_scores)

                    engagement_payload = {}
                    likes_value = parse_optional_int(upd_likes, "Likes")
                    shares_value = parse_optional_int(upd_shares, "Shares")
                    views_value = parse_optional_int(upd_views, "Views")
                    if likes_value is not None:
                        engagement_payload["likes"] = likes_value
                    if shares_value is not None:
                        engagement_payload["shares"] = shares_value
                    if views_value is not None:
                        engagement_payload["views"] = views_value
                    if engagement_payload:
                        payload["engagement"] = engagement_payload

                    if upd_comments.strip():
                        payload["comments"] = parse_comments(upd_comments)

                if payload is not None:
                    if not payload:
                        st.error("Provide at least one field to update.")
                    else:
                        response = requests.put(
                            f"{API_BASE_URL}/articles/{article_id.strip()}",
                            json=payload,
                            timeout=15,
                        )
                        if response.status_code == 200:
                            st.success("Article updated successfully.")
                        else:
                            st.error(f"Update failed: {response.text}")
        except ValueError as error:
            st.error(f"Invalid input: {error}")

with delete_tab:
    st.subheader("Delete Uploaded Article")
    article_id = st.text_input("Article ID")

    if st.button("Delete", key="btn_delete"):
        if not article_id.strip():
            st.error("Article ID is required.")
        else:
            response = requests.delete(f"{API_BASE_URL}/articles/{article_id.strip()}", timeout=10)
            if response.status_code == 200:
                data = response.json()
                st.success(data.get("message", "Article deleted"))
            else:
                st.error(f"Delete failed: {response.text}")
