args <- commandArgs(trailingOnly = TRUE)

parse_args <- function(args) {
  parsed <- list()
  i <- 1
  while (i <= length(args)) {
    key <- args[[i]]
    if (!startsWith(key, "--")) {
      stop(sprintf("Unexpected argument: %s", key), call. = FALSE)
    }
    if (i == length(args)) {
      stop(sprintf("Missing value for %s", key), call. = FALSE)
    }
    parsed[[substring(key, 3)]] <- args[[i + 1]]
    i <- i + 2
  }
  parsed
}

`%||%` <- function(left, right) {
  if (is.null(left) || length(left) == 0) {
    right
  } else {
    left
  }
}

write_report <- function(dataframe, output_dir, name) {
  path <- file.path(output_dir, sprintf("%s.csv", name))
  utils::write.csv(dataframe, path, row.names = FALSE)
}

show_table <- function(title, dataframe) {
  cat(sprintf("\n=== %s ===\n", title))
  print(dataframe)
}

parsed <- parse_args(args)
if (is.null(parsed$`input-jsonl`) || is.null(parsed$`output-dir`)) {
  stop(
    "Usage: Rscript article_analytics.R --input-jsonl rows.jsonl --output-dir sample_data/spark_reports",
    call. = FALSE
  )
}

suppressPackageStartupMessages(library(jsonlite))
suppressPackageStartupMessages(library(sparklyr))
suppressPackageStartupMessages(library(dplyr))
spark_version <- Sys.getenv("SPARK_VERSION", "3.5.1")

rows <- stream_in(file(parsed$`input-jsonl`), verbose = FALSE)
if (nrow(rows) == 0) {
  stop("No articles found to analyze. Upload a few articles first.", call. = FALSE)
}

dir.create(parsed$`output-dir`, recursive = TRUE, showWarnings = FALSE)

articles_df <- data.frame(
  article_id = rows$article_id,
  title = rows$title,
  content = rows$content,
  content_length = as.numeric(rows$content_length),
  published_date = rows$published_date,
  category = rows$category,
  author_name = rows$author_name,
  publisher_name = rows$publisher_name,
  publisher_house = rows$publisher_house,
  bias_label = rows$bias_label,
  bias_score = as.numeric(rows$bias_score),
  graph_confidence = as.numeric(rows$graph_confidence),
  likes = as.numeric(rows$likes),
  shares = as.numeric(rows$shares),
  views = as.numeric(rows$views),
  stringsAsFactors = FALSE
)

keywords_nested <- rows$keywords %||% vector("list", length = nrow(rows))
keyword_rows <- do.call(
  rbind,
  lapply(seq_len(nrow(rows)), function(index) {
    article_keywords <- keywords_nested[[index]] %||% character(0)
    article_keywords <- as.character(article_keywords)
    article_keywords <- article_keywords[nzchar(trimws(article_keywords))]
    if (length(article_keywords) == 0) {
      return(NULL)
    }
    data.frame(
      article_id = rep(rows$article_id[[index]], length(article_keywords)),
      keyword = article_keywords,
      stringsAsFactors = FALSE
    )
  })
)
if (is.null(keyword_rows)) {
  keyword_rows <- data.frame(article_id = character(0), keyword = character(0))
}

spark_config <- spark_config()
spark_config[["sparklyr.shell.driver-memory"]] <- Sys.getenv("SPARK_DRIVER_MEMORY", "1g")
spark_config$spark.ui.showConsoleProgress <- "false"

sc <- spark_connect(
  master = Sys.getenv("SPARK_MASTER", "local[*]"),
  app_name = Sys.getenv("SPARK_APP_NAME", "PoliticalNewsAnalyticsR"),
  version = spark_version,
  config = spark_config
)
on.exit(spark_disconnect(sc), add = TRUE)

articles_tbl <- copy_to(sc, articles_df, name = "articles_analytics", overwrite = TRUE)
keywords_tbl <- copy_to(sc, keyword_rows, name = "article_keywords", overwrite = TRUE)

publisher_counts <- articles_tbl %>%
  group_by(publisher_name) %>%
  summarise(article_count = n(), .groups = "drop") %>%
  arrange(desc(article_count), publisher_name) %>%
  collect()

category_counts <- articles_tbl %>%
  group_by(category) %>%
  summarise(article_count = n(), .groups = "drop") %>%
  arrange(desc(article_count), category) %>%
  collect()

bias_distribution <- articles_tbl %>%
  group_by(bias_label) %>%
  summarise(article_count = n(), .groups = "drop") %>%
  arrange(desc(article_count), bias_label) %>%
  collect()

engagement_by_category <- articles_tbl %>%
  group_by(category) %>%
  summarise(
    avg_views = round(mean(views, na.rm = TRUE), 2),
    avg_likes = round(mean(likes, na.rm = TRUE), 2),
    avg_shares = round(mean(shares, na.rm = TRUE), 2),
    .groups = "drop"
  ) %>%
  arrange(desc(avg_views), category) %>%
  collect()

top_keywords <- keywords_tbl %>%
  group_by(keyword) %>%
  summarise(keyword_count = n(), .groups = "drop") %>%
  arrange(desc(keyword_count), keyword) %>%
  collect()

publisher_bias <- articles_tbl %>%
  group_by(publisher_name, bias_label) %>%
  summarise(article_count = n(), .groups = "drop") %>%
  arrange(publisher_name, desc(article_count), bias_label) %>%
  collect()

dataset_summary <- articles_tbl %>%
  summarise(
    total_articles = n(),
    avg_content_length = round(mean(content_length, na.rm = TRUE), 2),
    max_content_length = max(content_length, na.rm = TRUE),
    avg_graph_confidence = round(mean(graph_confidence, na.rm = TRUE), 4)
  ) %>%
  collect()

show_table("Publisher Article Counts", publisher_counts)
show_table("Category Article Counts", category_counts)
show_table("Bias Distribution", bias_distribution)
show_table("Average Engagement By Category", engagement_by_category)
show_table("Top Keywords", top_keywords)
show_table("Publisher vs Bias Label", publisher_bias)
show_table("Dataset Summary", dataset_summary)

write_report(publisher_counts, parsed$`output-dir`, "publisher_counts")
write_report(category_counts, parsed$`output-dir`, "category_counts")
write_report(bias_distribution, parsed$`output-dir`, "bias_distribution")
write_report(engagement_by_category, parsed$`output-dir`, "engagement_by_category")
write_report(top_keywords, parsed$`output-dir`, "top_keywords")
write_report(publisher_bias, parsed$`output-dir`, "publisher_bias")
write_report(dataset_summary, parsed$`output-dir`, "dataset_summary")
