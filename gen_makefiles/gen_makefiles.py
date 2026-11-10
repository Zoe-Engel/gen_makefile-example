#!/usr/bin/env python3
import itertools
import json
import os
import re
import sys

RESERVED = {"all", "clean", "liststale", "cleanstale", "help", "Makefile"}
NAME = re.compile(r"^[A-Za-z0-9_+-]+$")
KEY = re.compile(r"^[A-Za-z0-9_.+-]+$")
VARIABLE = re.compile(r"^([A-Z_][A-Z0-9_]*)\s*=\s*(.*)$")
SECTION = re.compile(r"^\[([a-z]+)\]$")
SECTIONS = ["variables", "places", "transitions", "implementations"]
TRANSITION = re.compile(r"^([A-Za-z0-9_]+)(?:\[([^\]]+)\])?$")
IMPLEMENTATIONS = re.compile(r"^\{([^{}]*)\}(?:\s*\{([^{}]*)\})?$")
INTERPRETERS = {".py": "$(PYTHON)", ".sh": "bash", ".R": "Rscript", ".r": "Rscript"}

def fail(message):
    sys.exit(f"gen_makefiles: {message}")


def parse_spec(path):
    spec = {"variables": {}, "places": {}, "transitions": {}, "impls": {}}
    section = None
    with open(path) as f:
        for number, raw in enumerate(f, 1):
            line = raw.split("#", 1)[0].strip()
            if not line:
                continue
            header = SECTION.match(line)
            if header:
                section = header.group(1)
                if section not in SECTIONS:
                    fail(f"{path}:{number}: unknown section [{section}], expected one of {['[' + s + ']' for s in SECTIONS]}")
                continue
            where = f"{path}:{number}"
            if section is None:
                fail(f"{where}: '{line}' is outside a section; start with [variables], [places], [transitions] or [implementations]")
            if section == "variables":
                variable = VARIABLE.match(line)
                if not variable:
                    fail(f"{where}: expected 'NAME = value' in [variables]")
                spec["variables"][variable.group(1)] = variable.group(2)
            elif section == "places":
                parse_place(spec, line, where)
            else:
                if ":" not in line:
                    fail(f"{where}: expected 'name: ...' in [{section}]")
                head, body = (part.strip() for part in line.split(":", 1))
                if section == "transitions":
                    t = parse_transition(head, body, where)
                    if t["name"] in spec["transitions"]:
                        fail(f"{where}: transition '{t['name']}' is declared twice")
                    spec["transitions"][t["name"]] = t
                else:
                    spec["impls"].setdefault(head, []).extend(parse_impls(head, body, where))
    spec["sources"] = {name: p["path"] for name, p in spec["places"].items() if p["path"]}
    return spec


def parse_place(spec, line, where):
    parts = line.split()
    if len(parts) > 2:
        fail(f"{where}: expected 'place' or 'place  path' in [places]")
    token = parts[0]
    is_dir = token.endswith("/")
    name, ext = (token[:-1], "") if is_dir else os.path.splitext(token)
    if not NAME.match(name):
        fail(f"{where}: place '{name}' may only contain letters, digits and _ + -")
    if name in spec["places"]:
        fail(f"{where}: place '{name}' is declared twice")
    spec["places"][name] = {"path": parts[1] if len(parts) == 2 else None, "dir": is_dir, "ext": ext}


def parse_transition(head, body, where):
    match = TRANSITION.match(head)
    if not match:
        fail(f"{where}: bad transition name '{head}'")
    inputs, outputs, current = [], [], None
    for token in body.split():
        if token in ("-i", "-o"):
            current = inputs if token == "-i" else outputs
        elif current is None:
            fail(f"{where}: '{token}' must follow -i or -o")
        else:
            current.append(token)
    parsed_inputs = []
    for token in inputs:
        place, _, select = token.partition("@")
        parsed_inputs.append((place, select.split(",") if select else None))
    return {"name": match.group(1), "foreach": match.group(2), "inputs": parsed_inputs, "outputs": outputs}


def read_table(path):
    if path.endswith(".json"):
        with open(path) as f:
            return json.load(f)
    with open(path) as f:
        lines = [line.rstrip("\n") for line in f if line.strip()]
    return {line.split("\t", 1)[0]: line for line in lines[1:]}, lines[0]


def table_keys(path):
    table = read_table(path)
    keys = list(table.keys()) if path.endswith(".json") else list(table[0].keys())
    for key in keys:
        if not KEY.match(key):
            fail(f"key '{key}' in table {path} may only contain letters, digits and _ . + -")
    return keys


def slice_content(path, key):
    if path.endswith(".json"):
        return json.dumps({key: read_table(path)[key]}, indent=4) + "\n"
    rows, header = read_table(path)
    return f"{header}\n{rows[key]}\n"


def write_if_changed(path, content):
    if os.path.exists(path):
        with open(path) as f:
            if f.read() == content:
                return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(content)


def stem(path):
    return os.path.splitext(os.path.basename(path))[0]


def parse_impls(head, body, where):
    match = IMPLEMENTATIONS.match(body)
    if not match:
        fail(f"{where}: expected '{head}: {{script, ...}}' or '{head}: {{script, ...}} {{config, ...}}' in [implementations]")
    scripts, configs = ([entry.strip() for entry in group.split(",") if entry.strip()] for group in (match.group(1), match.group(2) or ""))
    return [{"script": script, "config": config, "label": stem(config or script)} for script in scripts for config in configs or [None]]


def check_arc(spec, t, name, direction):
    if name not in spec["places"]:
        declared = [p for p in spec["places"] if name.startswith(p)]
        hint = f"; refer to places by their name without extension or '/', e.g. '{declared[0]}'" if declared else ""
        fail(f"transition '{t['name']}' {direction} '{name}', which is not declared in [places]{hint}")
    return name


def validate(spec):
    transitions = spec["transitions"]
    places = spec["places"]
    producers = {}
    for t in transitions.values():
        if t["name"] in RESERVED:
            fail(f"transition name '{t['name']}' is reserved")
        if t["name"] not in spec["impls"]:
            fail(f"transition '{t['name']}' has no entry in [implementations] ('{t['name']}: {{script, ...}} {{config, ...}}')")
        labels = [impl["label"] for impl in spec["impls"][t["name"]]]
        if len(set(labels)) != len(labels):
            fail(f"alternatives of '{t['name']}' are named after their config file (or script without config) and need distinct names, got {labels}")
        if t["foreach"] and t["foreach"] not in spec["sources"]:
            fail(f"transition '{t['name']}' iterates over '{t['foreach']}', which is not a place with a path in [places]")
        for name in t["outputs"]:
            check_arc(spec, t, name, "writes")
            if name in producers:
                fail(f"place '{name}' is written by both '{producers[name]}' and '{t['name']}'")
            if places[name]["path"]:
                fail(f"place '{name}' has a path in [places], so it is a source and cannot be written by '{t['name']}'")
            producers[name] = t["name"]
        for name, _ in t["inputs"]:
            check_arc(spec, t, name, "reads")
    for name in spec["impls"]:
        if name not in transitions:
            fail(f"[implementations] lists unknown transition '{name}'")
    read = {place for t in transitions.values() for place, _ in t["inputs"]} | {t["foreach"] for t in transitions.values()}
    for name, place in places.items():
        if not place["path"] and name not in producers:
            fail(f"place '{name}' has no path and no transition writes it")
        if name not in read and name not in producers:
            fail(f"place '{name}' is not connected to any transition")
    for t in transitions.values():
        for name, select in t["inputs"]:
            if name in spec["sources"]:
                if select:
                    fail(f"'{name}@...' in '{t['name']}': only produced places have implementations to select")
                continue
            producer = transitions[producers[name]]
            if producer["foreach"] and producer["foreach"] != t["foreach"]:
                fail(
                    f"transition '{t['name']}' reads '{name}', which '{producer['name']}' produces once per "
                    f"'{producer['foreach']}' entry; mark it as '{t['name']}[{producer['foreach']}]'"
                )
            for choice in select or []:
                if choice not in [impl["label"] for impl in spec["impls"][producer["name"]]]:
                    fail(f"'{name}@{choice}' in '{t['name']}': '{producer['name']}' has no implementation '{choice}'")
    return transitions, producers


def topological_order(transitions, producers):
    order, visiting = [], set()

    def visit(name):
        if name in order:
            return
        if name in visiting:
            fail(f"cycle through transition '{name}'")
        visiting.add(name)
        for place, _ in transitions[name]["inputs"]:
            if place in producers:
                visit(producers[place])
        visiting.discard(name)
        order.append(name)

    for name in transitions:
        visit(name)
    return order


def build_runs(spec, transitions, producers, order):
    runs = {}
    for name in order:
        t = transitions[name]
        impls = spec["impls"][name]
        keys = table_keys(spec["sources"][t["foreach"]]) if t["foreach"] else [None]
        runs[name] = []
        for key in keys:
            candidates = [input_candidates(spec, t, key, place, select, producers, runs) for place, select in t["inputs"]]
            for combination in itertools.product(*candidates):
                choices = merge_choices(combination)
                if choices is None:
                    continue
                for impl in impls:
                    runs[name].append(make_run(spec, t, key, impl, dict(choices, **{name: impl["label"]}), combination, order))
    return runs


def slice_path(spec, key, table):
    return os.path.join(".gen", "slices", key, os.path.basename(spec["sources"][table]))


def input_candidates(spec, t, key, name, select, producers, runs):
    if name in spec["sources"]:
        path = slice_path(spec, key, name) if name == t["foreach"] else spec["sources"][name]
        return [{"path": path, "dep": path, "choices": {}}]
    found = []
    for run in runs[producers[name]]:
        if run["key"] is not None and run["key"] != key:
            continue
        if select and run["impl"] not in select:
            continue
        found.append({"path": run["outputs"][name], "dep": run["outputs"][name], "choices": run["choices"]})
    return found


def merge_choices(combination):
    merged = {}
    for candidate in combination:
        for transition, impl in candidate["choices"].items():
            if merged.get(transition, impl) != impl:
                return None
            merged[transition] = impl
    return merged


def make_run(spec, t, key, impl, choices, combination, order):
    branch = "".join("@" + choices[name] for name in order if name in choices and choices[name] != spec["impls"][name][0]["label"])
    run_id = (key or t["name"]) + branch
    outputs = {name: os.path.join("out", name, (key or name) + branch + spec["places"][name]["ext"]) for name in t["outputs"]}
    return {
        "transition": t["name"],
        "key": key,
        "script": impl["script"],
        "config": impl["config"],
        "impl": impl["label"],
        "choices": choices,
        "id": run_id,
        "cmd_file": os.path.join(".gen", "cmd", t["name"], os.path.basename(outputs[t["outputs"][0]]) + ".cmd"),
        "inputs": [c["path"] for c in combination],
        "deps": sorted({c["dep"] for c in combination}),
        "outputs": outputs,
        "output_dirs": [path for name, path in outputs.items() if spec["places"][name]["dir"]],
    }


def command(run):
    interpreter = INTERPRETERS.get(os.path.splitext(run["script"])[1])
    parts = ([interpreter] if interpreter else []) + [run["script"]]
    if run["inputs"]:
        parts += ["-i"] + run["inputs"]
    parts += ["-o"] + list(run["outputs"].values())
    if run["config"]:
        parts += ["-c", run["config"]]
    return " ".join(parts)


def render_run(run):
    outputs = list(run["outputs"].values())
    # Make 4.2 has no grouped targets (&:), but a pattern rule with several targets runs its recipe once for all of
    # them; every output starts with "out/", so "%ut/..." turns the literal paths into such a rule with stem "o".
    targets = outputs if len(outputs) == 1 else ["%" + path[1:] for path in outputs]
    dirs = sorted({os.path.dirname(p) for p in outputs} | set(run["output_dirs"]))
    prereqs = run["deps"] + [run["script"]] + ([run["config"]] if run["config"] else []) + [run["cmd_file"]]
    lines = [f"{' '.join(targets)}: {' '.join(prereqs)}"]
    if run["output_dirs"]:
        lines.append(f"\t@rm -rf {' '.join(run['output_dirs'])}")
    lines += [
        f"\t@mkdir -p {' '.join(dirs)}",
        f"\t{command(run)} || {{ rm -rf {' '.join(outputs)}; exit 1; }}",
        f"\t@touch {' '.join(outputs)}",
        "",
    ]
    return "\n".join(lines)


def run_targets(selected):
    return " ".join(path for run in selected for path in run["outputs"].values())


def render_makefile(spec_name, generator, spec, runs, order):
    all_runs = [run for name in order for run in runs[name]]
    keys = sorted({run["key"] for run in all_runs if run["key"]})
    clashes = set(keys) & (set(order) | RESERVED)
    if clashes:
        fail(f"table keys clash with transition or target names: {sorted(clashes)}")
    for name in order:
        ids = [run["id"] for run in runs[name]]
        if len(set(ids)) != len(ids):
            fail(f"two runs of '{name}' get the same name; give implementations of different transitions distinct file names")

    variables = dict({"PYTHON": "python3"}, **spec["variables"])
    tables = sorted({spec["sources"][t["foreach"]] for t in spec["transitions"].values() if t["foreach"]})
    gen = f"python3 {generator} {spec_name}"
    lines = [f"# Generated by gen_makefiles.py from {spec_name}. Edit {spec_name} instead; this file regenerates itself.",
             "SHELL := /usr/bin/env bash", ".DELETE_ON_ERROR:", ".DEFAULT_GOAL := all", ""]
    lines += [f"{name} ?= {value}" for name, value in variables.items()]
    lines += [f"export {' '.join(variables)}", "", f"Makefile: {' '.join([spec_name, generator] + tables)}", f"\t{gen}", "",
              ".gen/cmd/% .gen/slices/%:", f"\t{gen}", ""]
    lines += [render_run(run) for run in all_runs]

    place_dirs = " ".join(os.path.join("out", name) for name in sorted({name for run in all_runs for name in run["outputs"]}))
    lines += [f"TARGETS := {run_targets(all_runs)}",
              f"STALE_PLACES = $(filter-out {place_dirs},$(wildcard out/*))",
              "STALE = $(STALE_PLACES) $(filter-out $(TARGETS) $(addsuffix /%,$(STALE_PLACES)),$(wildcard out/*/*))", ""]
    lines += [".PHONY: all clean liststale cleanstale help " + " ".join(order + keys), "all: $(TARGETS)"]
    for name in order:
        lines.append(f"{name}: {run_targets(runs[name])}")
    for key in keys:
        lines.append(f"{key}: {run_targets(run for run in all_runs if run['key'] == key)}")
    lines += ["clean:", "\trm -rf out",
              "liststale:", "\t@$(if $(strip $(STALE)),printf '%s\\n' $(STALE),echo 'nothing stale')",
              "cleanstale:", "\t$(if $(strip $(STALE)),rm -rf $(STALE),@echo 'nothing stale')",
              "help:",
              "\t@echo 'make                build everything'",
              f"\t@echo 'make <transition>   one transition: {' '.join(order)}'"]
    if keys:
        lines.append(f"\t@echo 'make <key>          everything for one table entry: {' '.join(keys)}'")
    lines += ["\t@echo 'make liststale      list files in out/ that no current run produces'",
              "\t@echo 'make cleanstale     delete them'",
              "\t@echo 'make clean          delete out/'", ""]
    return "\n".join(lines)


def main():
    if len(sys.argv) != 2:
        sys.exit("usage: gen_makefiles.py <pipeline.spec>")
    spec_path = os.path.abspath(sys.argv[1])
    root = os.path.dirname(spec_path)
    generator = os.path.relpath(os.path.abspath(__file__), root)
    os.chdir(root)

    spec = parse_spec(spec_path)
    transitions, producers = validate(spec)
    order = topological_order(transitions, producers)
    runs = build_runs(spec, transitions, producers, order)

    for name in producers:
        os.makedirs(os.path.join("out", name), exist_ok=True)
    expected = set()
    for name in order:
        t = transitions[name]
        for run in runs[name]:
            write_if_changed(run["cmd_file"], command(run) + "\n")
            expected.add(run["cmd_file"])
            if t["foreach"]:
                path = slice_path(spec, run["key"], t["foreach"])
                write_if_changed(path, slice_content(spec["sources"][t["foreach"]], run["key"]))
                expected.add(path)
    for folder in (os.path.join(".gen", "cmd"), os.path.join(".gen", "slices")):
        for directory, _, files in os.walk(folder):
            for file in files:
                if os.path.join(directory, file) not in expected:
                    os.remove(os.path.join(directory, file))

    with open("Makefile", "w") as f:
        f.write(render_makefile(os.path.basename(spec_path), generator, spec, runs, order))
    print(f"gen_makefiles: {sum(len(r) for r in runs.values())} runs from {len(order)} transitions -> {os.path.join(root, 'Makefile')}")


if __name__ == "__main__":
    main()
