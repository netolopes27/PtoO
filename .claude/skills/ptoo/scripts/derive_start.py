#!/usr/bin/env python
"""Deriva o `## start` da memory.md a partir do log de calibrações runs.tsv.

O runs.tsv (na pasta da skill) é o banco de treino da /ptoo: append-only, SEM teto de
linhas, **1 linha por PASSE** de cada laço (vencedor marcado com winner=1; linhas com
pass=0 são sementes legado sem trajetória). Este script agrega e imprime:
  1. o `## start` sugerido (medianas dos vencedores; min-dist por FORMA; shadow por maioria);
  2. a tabela tamanho × min-dist por forma — p/ enxergar a razão, se ela existir;
  3. eficiência: passes até cruzar o gate, por laço com trajetória (pass > 0).

Só stdlib. Rode com o Python do venv por convenção do repo.

Uso:
  derive_start.py [--runs PATH]
"""
import argparse
import csv
import os
import statistics
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

DEFAULT_RUNS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "runs.tsv")


def fnum(v):
    """'-' e vazio viram None; o resto vira float."""
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def size_bin(w, h):
    m = max(w, h)
    if m < 50:
        return "<50"
    if m < 80:
        return "50-80"
    if m < 120:
        return "80-120"
    return ">=120"


def median_of(rows, key):
    vals = [v for v in (fnum(r.get(key)) for r in rows) if v is not None]
    return statistics.median(vals) if vals else None


def fmt(v):
    return "?" if v is None else f"{v:g}"


def main():
    ap = argparse.ArgumentParser(description="Agrega runs.tsv e sugere o ## start da memory.md")
    ap.add_argument("--runs", default=DEFAULT_RUNS, help="caminho do runs.tsv")
    args = ap.parse_args()

    with open(args.runs, "r", encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh, delimiter="\t"))
    winners = [r for r in rows if r.get("winner") == "1"]
    print(f"runs.tsv: {len(rows)} linhas · {len(winners)} vencedores")
    if not winners:
        print("Nada a derivar ainda — registre laços primeiro.")
        return

    print("\n## start sugerido (transcrever p/ a memory.md; symmetry segue CONDICIONAL por-peça)")
    shadows = [r["shadow"] for r in winners if r.get("shadow") not in (None, "", "-")]
    shadow = max(set(shadows), key=shadows.count) if shadows else None
    if shadow:
        print(f"  --shadow {shadow}  (maioria {shadows.count(shadow)}/{len(shadows)})")
    by_shape = {}
    for r in winners:
        by_shape.setdefault(r.get("shape") or "?", []).append(r)
    for shape in sorted(by_shape):
        md = median_of(by_shape[shape], "min_dist")
        print(f"  --min-dist [{shape}]: {fmt(md)}  (n={len(by_shape[shape])})")
    for key, flag in (("smooth_mm", "--smooth-mm"), ("pocket_eps", "--pocket-eps"),
                      ("mask_smooth_mm", "--mask-smooth-mm")):
        print(f"  {flag} {fmt(median_of(winners, key))}")
    print(f"  n={len(winners)} vencedores")

    print("\n## tamanho × min-dist (vencedores — a razão, se existir, aparece aqui)")
    print(f"  {'forma':<10}  {'bin':<7}  {'maior lado':>10}  {'min-dist':>8}  objeto")
    for r in sorted(winners, key=lambda r: (r.get("shape") or "", fnum(r.get("obj_w_mm")) or 0)):
        w, h = fnum(r.get("obj_w_mm")), fnum(r.get("obj_h_mm"))
        if w is None or h is None:
            continue
        print(f"  {r.get('shape') or '?':<10}  {size_bin(w, h):<7}  {max(w, h):>10.1f}"
              f"  {r.get('min_dist') or '?':>8}  {r.get('object') or '?'}")
    for shape in sorted(by_shape):
        bins = {}
        for r in by_shape[shape]:
            w, h = fnum(r.get("obj_w_mm")), fnum(r.get("obj_h_mm"))
            if w is not None and h is not None:
                bins.setdefault(size_bin(w, h), []).append(r)
        for b in sorted(bins):
            md = median_of(bins[b], "min_dist")
            print(f"  mediana {shape} {b}: min-dist {fmt(md)} (n={len(bins[b])})")

    print("\n## eficiência (passes até o gate; só laços com trajetória, pass > 0)")
    laps = {}
    for r in rows:
        p = fnum(r.get("pass"))
        if not p:  # 0, '-' ou vazio = semente legado sem trajetória
            continue
        laps.setdefault((r.get("date"), r.get("photo"), r.get("object")), []).append(r)
    if not laps:
        print("  nenhum laço com trajetória ainda (só sementes legado, pass=0)")
        return
    to_gate = []
    for (date, photo, obj), rs in sorted(laps.items()):
        total = max(int(fnum(r["pass"])) for r in rs)
        gated = [int(fnum(r["pass"])) for r in rs if r.get("gate") == "1"]
        if gated:
            to_gate.append(min(gated))
            print(f"  {obj} ({date}): gate no passe {min(gated)} de {total}")
        else:
            print(f"  {obj} ({date}): NÃO cruzou o gate em {total} passes")
    if to_gate:
        print(f"  mediana passes-até-gate: {statistics.median(to_gate):g} (n={len(to_gate)})")


if __name__ == "__main__":
    main()
