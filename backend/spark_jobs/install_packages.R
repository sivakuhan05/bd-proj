repos <- "https://cloud.r-project.org"
packages <- c("sparklyr", "dplyr", "jsonlite")
default_spark_version <- "3.5.1"

user_library <- Sys.getenv("R_LIBS_USER")
if (!nzchar(user_library)) {
  user_library <- path.expand("~/R/library")
}

dir.create(user_library, recursive = TRUE, showWarnings = FALSE)
.libPaths(c(user_library, .libPaths()))

install.packages(packages, repos = repos, lib = user_library)

if (!requireNamespace("sparklyr", quietly = TRUE, lib.loc = user_library)) {
  stop(
    paste(
      "Failed to install sparklyr.",
      "On Ubuntu, install build deps then retry:",
      "sudo apt-get install -y r-base-dev libcurl4-openssl-dev libssl-dev libxml2-dev"
    ),
    call. = FALSE
  )
}

library("sparklyr", lib.loc = user_library, character.only = TRUE)

spark_version <- Sys.getenv("SPARK_VERSION")
if (!nzchar(spark_version)) {
  spark_version <- default_spark_version
}

cat(sprintf("Installing Spark runtime version: %s\n", spark_version))
sparklyr::spark_install(version = spark_version)

cat("Note: sparklyr package loaded successfully.\n")
cat("Spark runtime installation completed.\n")
