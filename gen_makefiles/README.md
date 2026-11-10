# gen_makefiles

`gen_makefiles.py` reads a pipeline description (`pipeline.spec`) and writes a Makefile that runs it. The pipeline is a Petri net: places hold data, transitions are scripts that read places and write places.  
Make then decides what needs to run.

`krautwurst_example/` is a short example pipeline.

```bash
python3 ../gen_makefiles/gen_makefiles.py pipeline.spec   # once. afterwards the Makefile regenerates itself
make            # build everything
make help       # list targets
```

Requirements: Python >= 3.6 for the generator and GNU make >= 4.2.
The scripts can use whatever environment they need (see `[variables]`).

### `[variables]`

```
PYTHON	= biopython 
FUZZSYS_THREADS	= 4
```

These become make variables and are exported to every script. Override one per run with `make FUZZSYS_THREADS=8`.

### `[places]`

```
expression	data/krautwurst.h5ad
comparisons	data/all_comparisons.json
cond_matrix.tsv
cond_fuzz_concept/
```

- A place with a path is a root place: input data that exists before the pipeline runs. No transition may write it.
- A place without a path is produced by exactly one transition. It gets the folder `out/<place>/`.
  - `name.ext` is a file place; each run writes one file `out/<place>/<run>.ext`.
  - `name/` is a directory place; each run writes one folder `out/<place>/<run>/` and may put anything in it.

Transitions refer to places by name only (`cond_matrix`, not `cond_matrix.tsv`).

### `[transitions]`

```
submatrix[comparisons]:	-i expression comparisons -o cond_matrix ctrl_matrix
pooled_log2fc:	-i expression comparisons -o log2FC
```

`name: -i <input places> -o <output places>`. A transition may have several outputs.
`[table]` after the name makes it run once per entry of that table (see Iteration).

### `[implementations]`

```
submatrix:	{scripts/prepare_submatrix.py}
gen_report:	{scripts/generate_report.py}	{configs/generate_report.json}
```

`transition: {scripts} {configs}`. The config list is optional. Every listed script runs with every listed config, and each pair is one alternative (see Alternatives).

## What a script gets called with

```
<interpreter> script -i <input paths> -o <output paths> [-c <config>]
```

Inputs and outputs come in the order the spec lists the places. The interpreter is chosen by extension: `.py` -> `$(PYTHON)`, `.sh` -> `bash`, `.R` -> `Rscript`, anything else is executed directly.
Scripts know nothing about places or the out/ layout; they only see paths.
Parameters go into the JSON config, not into the script, so the same script can run with different settings.

For example, fuzzsys_cond for the comparison test3 runs:

```
bash scripts/fuzzsys.sh -i out/cond_matrix/test3.tsv -o out/cond_fuzz_concept/test3 out/cond_fuzz_vals/test3 -c configs/fuzzsys_expression.json
```

A script that writes a directory output gets an empty directory. If a script fails, all of that run's outputs are deleted.

## Iteration

`submatrix[comparisons]` runs `submatrix` once per key of the root place `comparisons`.
The table is either a JSON object (keys = top-level keys) or a TSV (keys = first column, first line is the header).
Keys may contain letters, digits and `_ . + -`.

- Each run receives only its own entry, as a one-entry copy of the table under `.gen/slices/<key>/`.
If the table itself is not an input, the run just gets the key in its output paths.
- Outputs are named after the key: `out/cond_matrix/test3.tsv`.
- A transition that reads a per-key output must iterate over the same table; the generator refuses otherwise.
The run for `test3` then reads only `test3`'s outputs.
- A transition without `[...]` runs once and reads the full table, like `pooled_log2fc`.

Editing one entry of the table reruns only that entry's chain, plus transitions that read the whole table.

## Alternatives

Listing more than one script or config gives a transition alternatives:

```
fuzzsys_cond:	{scripts/fuzzsys.sh}	{configs/default.json, configs/strict.json}
fuzzsys_cond:	{scripts/other_fuzzifier.py}	{configs/other.json}
```

- Each alternative is named after its config file, or after its script if it has no config (`default`, `strict`, `other`). Names must be unique within a transition.
- The first alternative is the default and writes unsuffixed outputs (`out/cond_fuzz_vals/test3/`). The others append `@<name>` (`out/cond_fuzz_vals/test3@strict/`). Add new alternatives after the existing ones, so existing outputs keep their names.
- Repeat the transition on another line when a script needs a different kind of config.
- Downstream transitions run once per alternative, and the suffixes carry through (`out/reports/test3@strict/`).
- To consume only some alternatives, select them on the input: `-i cond_fuzz_concept@strict` or `@default,strict`.

## When things rerun

A run is redone when any of these is newer than its outputs:
its inputs, its script, its config, or its command line. Each run's command is stored in `.gen/cmd/` and only rewritten when it changes.

So editing a config reruns that transition and everything downstream. Touching the spec without changing a command reruns nothing. The Makefile regenerates itself when the spec, the generator or an iteration table changes.

Not detected: deleting a single file inside an output directory. Delete the directory instead.

## Make targets

| Target | Does |
|---|---|
| `make` | build everything |
| `make <transition>` | all runs of one transition, plus what they need |
| `make <key>` | everything for one table entry, e.g. `make test3` |
| `make liststale` | list files in `out/` that no current run produces (e.g. after renaming an alternative) |
| `make cleanstale` | delete them |
| `make clean` | delete `out/` |

`make -j<N>` runs N steps in parallel. Avoid `make -t`, which creates empty files where output directories should be.

## Errors the generator catches

Undeclared, unconnected or unwritten places; a place written twice; writing a root place; cycles; reading a per-key output without the matching `[table]`; selecting an alternative that does not exist; duplicate alternative names; unknown sections.