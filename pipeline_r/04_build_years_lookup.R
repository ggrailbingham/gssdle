# build_years_lookup.R
# Produces years_lookup.csv: one row per variable × decade,
# listing every survey year the question was actually asked in that decade.
#
# Usage: Rscript build_years_lookup.R
#
# Input:  gss_filtered_extract.csv  (to get the list of variables we care about)
#         gss_all                    (from gssr package, for year-level data)
# Output: years_lookup.csv
#
# Columns in output:
#   variable  — GSS variable name
#   decade    — e.g. "1970s"
#   years_asked — comma-separated survey years, e.g. "1972, 1974, 1976"

library(gssr)
library(dplyr)

cat("Loading GSS data...\n")
data(gss_all)

cat("Loading filtered variable list...\n")
filtered <- read.csv("gss_filtered_extract.csv", stringsAsFactors = FALSE)
vars <- unique(filtered$variable)
cat(sprintf("  %d unique variables to look up\n", length(vars)))

DECADES <- list(
  "1970s" = 1970:1979,
  "1980s" = 1980:1989,
  "1990s" = 1990:1999,
  "2000s" = 2000:2009,
  "2010s" = 2010:2019,
  "2020s" = 2020:2029
)

# Only keep vars that actually exist in gss_all
vars <- vars[vars %in% names(gss_all)]
cat(sprintf("  %d variables found in gss_all\n", length(vars)))

cat("Building year lookup...\n")
rows <- list()

for (var in vars) {
  # Get years where this variable has at least one non-NA response
  # (weight not required here — we just want to know if the question was asked)
  df <- gss_all %>%
    select(year, val = all_of(var)) %>%
    filter(!is.na(val))

  if (nrow(df) == 0) next

  for (dec_name in names(DECADES)) {
    yr_range <- DECADES[[dec_name]]
    years_in_dec <- df %>%
      filter(year %in% yr_range) %>%
      pull(year) %>%
      unique() %>%
      sort()

    if (length(years_in_dec) == 0) next

    rows[[length(rows) + 1]] <- data.frame(
      variable    = var,
      decade      = dec_name,
      years_asked = paste(years_in_dec, collapse = ", "),
      stringsAsFactors = FALSE
    )
  }
}

lookup <- do.call(rbind, rows)
cat(sprintf("Done: %d variable × decade rows\n", nrow(lookup)))

write.csv(lookup, "years_lookup.csv", row.names = FALSE)
cat("✅ Saved years_lookup.csv\n")

# Quick sanity check
cat("\nSample (grass):\n")
print(lookup[lookup$variable == "grass", ])
