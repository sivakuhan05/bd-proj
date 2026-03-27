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

escape_sql_string <- function(value) {
  gsub("'", "''", value, fixed = TRUE)
}

escape_regex <- function(value) {
  gsub("([][{}()+*^$|\\\\?.])", "\\\\\\1", value, perl = TRUE)
}

sum_term_hits_expr <- function(terms, column_name) {
  if (length(terms) == 0) {
    return("0")
  }

  pieces <- vapply(
    terms,
    function(term) {
      escaped_term <- escape_regex(tolower(term))
      sql_term <- escape_sql_string(escaped_term)
      sprintf(
        "((length(%s) - length(regexp_replace(%s, '%s', ''))) / %d)",
        column_name,
        column_name,
        sql_term,
        max(nchar(term, type = "chars"), 1)
      )
    },
    character(1)
  )
  paste(pieces, collapse = " + ")
}

parsed <- parse_args(args)
if (is.null(parsed$input) || is.null(parsed$output)) {
  stop("Usage: Rscript bias_batch.R --input input.json --output output.json", call. = FALSE)
}

suppressPackageStartupMessages(library(jsonlite))
suppressPackageStartupMessages(library(sparklyr))

payload <- fromJSON(parsed$input, simplifyVector = FALSE)
metadata <- payload$metadata
spark_version <- payload$spark_version %||% Sys.getenv("SPARK_VERSION", "3.5.1")

content <- as.character(metadata$content %||% "")
category <- as.character(metadata$category %||% "")
keywords <- unlist(metadata$keywords %||% list(), use.names = FALSE)
organizations <- unlist(metadata$organizations %||% list(), use.names = FALSE)
think_tanks <- unlist(metadata$think_tanks %||% list(), use.names = FALSE)

text <- paste(
  content,
  category,
  paste(keywords, collapse = " "),
  paste(organizations, collapse = " "),
  paste(think_tanks, collapse = " "),
  sep = " "
)
text <- trimws(tolower(text))

spark_config <- spark_config()
spark_config[["sparklyr.shell.driver-memory"]] <- payload$spark_driver_memory %||% "1g"
spark_config$spark.ui.showConsoleProgress <- "false"

sc <- spark_connect(
  master = payload$spark_master %||% "local[*]",
  app_name = payload$spark_app_name %||% "PoliticalNewsBiasSparkR",
  version = spark_version,
  config = spark_config
)
on.exit(spark_disconnect(sc), add = TRUE)

article_tbl <- copy_to(
  sc,
  data.frame(text = text, stringsAsFactors = FALSE),
  name = "article_text_bias",
  overwrite = TRUE
)
sdf_register(article_tbl, "article_text_bias")

left_expr <- sum_term_hits_expr(payload$left_terms %||% character(0), "text")
right_expr <- sum_term_hits_expr(payload$right_terms %||% character(0), "text")

query <- sprintf(
  paste(
    "SELECT",
    "CAST(ROUND(%s, 0) AS INT) AS left_hits,",
    "CAST(ROUND(%s, 0) AS INT) AS right_hits,",
    "CASE",
    "WHEN trim(regexp_replace(text, '[^a-z0-9\\\\s]', ' ')) = '' THEN 0",
    "ELSE size(split(trim(regexp_replace(text, '[^a-z0-9\\\\s]', ' ')), '\\\\s+'))",
    "END AS token_count",
    "FROM article_text_bias"
  ),
  left_expr,
  right_expr
)

metrics <- collect(spark_sql(sc, query))

left_hits <- max(as.integer(metrics$left_hits[[1]] %||% 0), 0L)
right_hits <- max(as.integer(metrics$right_hits[[1]] %||% 0), 0L)
token_count <- max(as.integer(metrics$token_count[[1]] %||% 0), 0L)
total_hits <- left_hits + right_hits

score <- 0
if (total_hits > 0) {
  score <- (right_hits - left_hits) / total_hits
}
score <- max(-1, min(1, score))

confidence <- 0.48 + (0.30 * abs(score)) + min(total_hits * 0.025, 0.18)
confidence <- max(0.35, min(0.94, confidence))

label <- "Center"
if (score <= -0.2) {
  label <- "Left"
} else if (score >= 0.2) {
  label <- "Right"
}

predicted_at <- format(Sys.time(), tz = "UTC", usetz = TRUE)
predicted_at <- sub(" UTC$", "Z", predicted_at)

result <- list(
  label = label,
  score = round(score, 6),
  confidence = round(confidence, 6),
  model_version = payload$model_version %||% "internal-lexical-r-spark-v1",
  predicted_at = predicted_at,
  diagnostics = list(
    engine = "sparklyr",
    left_hits = left_hits,
    right_hits = right_hits,
    total_hits = total_hits,
    token_count = token_count
  )
)

write_json(result, parsed$output, auto_unbox = TRUE, pretty = FALSE, null = "null")
