#Remove questions from the data extract with >10 response options. 
#Eliminates only ~12% of variables (including unusable pieces like weights, etc.) while eliminating ~90% of rows

library(dplyr)

df <- read.csv("gss_full_extract.csv")

vars_to_keep <- df %>%
  distinct(variable, n_responses) %>%
  filter(n_responses <= 10) %>%
  pull(variable)

df_filtered <- df %>%
  filter(variable %in% vars_to_keep)

write.csv(df_filtered, "gss_filtered_extract.csv", row.names = FALSE)


cat("\n============Distributions===============\n")
cat("\nOld variable type distribution:\n")
print(table(df$var_type_guess[!duplicated(df$variable)]))


cat("\nNew variable type distribution:\n")
print(table(df_filtered$var_type_guess[!duplicated(df_filtered$variable)]))

cat("\n============Shape===============\n")

cat(sprintf("\nOld data set: %d rows (%d variables), %d rows/variable)\n",
            nrow(df), length(unique(df$variable)), round(nrow(df)/length(unique(df$variable)))))

cat(sprintf("\nNew data set: %d rows (%d variables, %d rows/variable)\n",
            nrow(df_filtered), length(unique(df_filtered$variable)),round(nrow(df_filtered)/length(unique(df_filtered$variable)))))


cat("\n============Output===============\n")
cat(sprintf("\n✅ Saved gss_filtered_extract.csv\n"))

random_rows <- df |>
  filter(var_type_guess == 'binary_other') |>
  slice_sample(n = 10, replace = FALSE) # set replace=TRUE if there might be fewer than 10 matches


view(random_rows)