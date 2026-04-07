# full_gss_extract.R
# Extracts everything needed for the game in one R script
# Output: gss_full_extract.csv

library(gssr)
library(gssrdoc)
library(dplyr)

cat("Loading GSS data...\n")
data(gss_all)

# Fix weights — use wtssnrps for 2021+
gss_all <- gss_all %>%
  mutate(weight = case_when(
    year >= 2021 & !is.na(wtssnrps) ~ wtssnrps,
    !is.na(wtssall)                 ~ wtssall,
    TRUE                            ~ NA_real_
  ))

cat(sprintf("GSS data loaded: %d rows, %d columns\n", 
            nrow(gss_all), ncol(gss_all)))

DECADES <- list(
  "1970s" = 1970:1979,
  "1980s" = 1980:1989,
  "1990s" = 1990:1999,
  "2000s" = 2000:2009,
  "2010s" = 2010:2019,
  "2020s" = 2020:2029
)
MIN_N_OVERALL <- 500
MIN_N_DECADE  <- 200

# ── Process one variable ──────────────────────────────────────────────────────
process_var <- function(var, gss_data, meta_row) {
  tryCatch({
    if (!var %in% names(gss_data)) return(NULL)
    
    # Clean subset
    df <- gss_data %>%
      select(year, weight, response = all_of(var)) %>%
      filter(!is.na(weight), !is.na(response))
    
    if (nrow(df) < MIN_N_OVERALL) return(NULL)
    
    # Get unique response labels (already human-readable in gssr)
    response_levels <- sort(unique(as.character(df$response)))
    
    # Compute weighted % for each response option — overall
    overall <- df %>%
      mutate(response = as.character(response)) %>%
      group_by(response) %>%
      summarise(w = sum(weight), n = n(), .groups = "drop") %>%
      mutate(pct = w / sum(w))
    
    # By decade
    decade_rows <- list()
    for (dec_name in names(DECADES)) {
      years <- DECADES[[dec_name]]
      sub   <- df %>% filter(year %in% years)
      if (nrow(sub) < MIN_N_DECADE) next
      
      dec_stats <- sub %>%
        mutate(response = as.character(response)) %>%
        group_by(response) %>%
        summarise(w = sum(weight), n = n(), .groups = "drop") %>%
        mutate(pct = w / sum(w), decade = dec_name)
      
      decade_rows[[dec_name]] <- dec_stats
    }
    
    # Flatten to one row per variable with response pcts as columns
    # Format: var, description, question, response_label, pct_overall,
    #         pct_1970s, pct_1980s, ..., n_overall, conditional_risk etc.
    
    # For each response option, create a column
    result_rows <- lapply(response_levels, function(resp) {
      pct_overall <- overall$pct[overall$response == resp]
      pct_overall <- if (length(pct_overall) == 0) 0 else pct_overall
      
      decade_pcts <- sapply(names(DECADES), function(dec) {
        if (is.null(decade_rows[[dec]])) return(NA_real_)
        p <- decade_rows[[dec]]$pct[decade_rows[[dec]]$response == resp]
        if (length(p) == 0) NA_real_ else p
      })
      
      row <- data.frame(
        variable       = var,
        description    = meta_row$description,
        question_text  = meta_row$question,
        value_labels   = meta_row$value_labels,
        response_label = resp,
        n_responses    = length(response_levels),
        var_type_guess = meta_row$var_type_guess,
        pct_overall    = round(pct_overall, 4),
        n_overall      = nrow(df),
        actual_iap     = meta_row$actual_iap,
        expected_iap   = meta_row$expected_iap,
        excess_iap     = meta_row$excess_iap,
        iap_full_years = meta_row$iap_full_years,
        conditional_risk = meta_row$conditional_risk,
        final_cond_risk = meta_row$final_cond_risk,
        n_years_asked  = meta_row$n_years_asked,
        subjects       = meta_row$subjects,
        module         = meta_row$module,
        norc_url       = meta_row$norc_url,
        stringsAsFactors = FALSE
      )
      
      # Add decade columns
      for (dec in names(DECADES)) {
        row[[paste0("pct_", dec)]] <- round(decade_pcts[dec], 4)
      }
      
      row
    })
    
    do.call(rbind, result_rows)
    
  }, error = function(e) NULL)
}

# ── Load metadata from previous extraction ────────────────────────────────────
cat("Loading variable metadata...\n")
meta <- read.csv("gss_variable_metadata.csv", stringsAsFactors = FALSE)

# Get variables to process
vars_to_process <- meta$variable[meta$variable %in% names(gss_all)]
cat(sprintf("Variables to process: %d\n", length(vars_to_process)))

# ── Main loop ─────────────────────────────────────────────────────────────────
cat("Processing variables...\n")
results <- vector("list", length(vars_to_process))

for (i in seq_along(vars_to_process)) {
  var      <- vars_to_process[i]
  meta_row <- meta[meta$variable == var, ]
  results[[i]] <- process_var(var, gss_all, meta_row)
  if (i %% 200 == 0) cat(sprintf("  %d / %d\n", i, length(vars_to_process)))
}

df_out <- do.call(rbind, Filter(Negate(is.null), results))
cat(sprintf("\nDone: %d rows (%d variables)\n",
            nrow(df_out), length(unique(df_out$variable))))

# ── Summary ───────────────────────────────────────────────────────────────────
cat("\nVariable type distribution:\n")
print(table(df_out$var_type_guess[!duplicated(df_out$variable)]))

cat("\nSample output for grass:\n")
print(df_out[df_out$variable == "grass", 
             c("variable","response_label","pct_overall",
               "pct_1970s","pct_1980s","pct_2000s","pct_2020s")])

write.csv(df_out, "gss_full_extract.csv", row.names = FALSE)
cat(sprintf("\n✅ Saved gss_full_extract.csv\n"))