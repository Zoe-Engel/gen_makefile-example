[variables]
# exported to every script
PYTHON	= biopython
FUZZSYS	= /mnt/extproj/projekte/modelling/interactive_fuzzifier/command_line
FUZZSYS_THREADS	= 4

[places]
# root places have a path. Every other place gets one folder out/<place>/, holding one entry per run:
# out/<place>/<comparison>.tsv for file places, out/<place>/<comparison>/ for directory places 
expression	data/krautwurst.h5ad
comparisons	data/all_comparisons.json
cond_matrix.tsv
ctrl_matrix.tsv
cond_fuzz_concept/
cond_fuzz_vals/
ctrl_fuzz_concept/
ctrl_fuzz_vals/
reports/
log2FC.tsv
overview_heatmap/
significance_heatmap/

[transitions]
# [comparisons] = iterate over all keys in the json of the place "comparisons" (has to be either json or tsv file)
submatrix[comparisons]:	-i expression comparisons -o cond_matrix ctrl_matrix
fuzzsys_cond[comparisons]:	-i cond_matrix -o cond_fuzz_concept cond_fuzz_vals
fuzzsys_ctrl[comparisons]:	-i ctrl_matrix -o ctrl_fuzz_concept ctrl_fuzz_vals
gen_report[comparisons]:	-i cond_matrix ctrl_matrix cond_fuzz_concept ctrl_fuzz_concept comparisons -o reports
pooled_log2fc:	-i expression comparisons -o log2FC
overview_script:	-i expression -o overview_heatmap
differential_analysis:	-i expression -o significance_heatmap

[implementations]
# {scripts} {configs}; every script runs with every config (passed as -c <config>), each pair is one
# alternative. Repeat a transition on another line to add alternatives that use a different config format
submatrix:	{scripts/prepare_submatrix.py}
fuzzsys_cond:	{scripts/fuzzsys.sh}	{configs/fuzzsys_expression.json}
fuzzsys_ctrl:	{scripts/fuzzsys.sh}	{configs/fuzzsys_expression.json}
gen_report:	{scripts/generate_report.py}	{configs/generate_report.json}
pooled_log2fc:	{scripts/prepare_pooled_log2FC.py}
overview_script:	{scripts/overview_heatmap.py}	{configs/overview_heatmap.json}
differential_analysis:	{scripts/differential_analysis.py}	{configs/differential_analysis.json}
