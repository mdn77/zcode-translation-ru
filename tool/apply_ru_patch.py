#!/usr/bin/env python3
"""Apply Russian UI localization to the ZCode desktop app.

What it does:
  1. Locates resources/app.asar of the installed ZCode.
  2. Extracts the archive with the official @electron/asar CLI (via npx).
  3. Finds two JS chunks by CONTENT (not by name, so it survives app updates):
     the IntlProvider chunk (message catalogs + locale logic) and the main
     renderer bundle (language dropdown + error-screen logic).
  4. Injects the Russian catalog from translations/ru-RU-catalog.json, registers
     the "ru" locale in the map/validator/system resolver, adds a "Русский" item
     to both language dropdowns, and wires the error-screen dictionary.
  5. Packs the tree back with @electron/asar (keeping node-pty/ssh2 binaries
     unpacked exactly like the original), verifies the result, and swaps it in
     after making a timestamped backup next to the original.

Usage:
  python apply_ru_patch.py                 # auto-detect ZCode, patch
  python apply_ru_patch.py --asar PATH     # explicit path to app.asar
  python apply_ru_patch.py --dry-run       # patch in memory, write nothing

Requires Python 3.8+ and Node.js (npx) on PATH. No pip dependencies.
"""
import argparse
import io
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import time

BT = chr(96)  # the JS bundle stores message values in backquote template literals
RU_LABEL = 'Русский'

# --------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------

def qx(s):
    return f'{BT}{s}{BT}'


# Regex building blocks for literal braces, f-string-safe by construction.
OB = f'[{chr(123)}]'
CB = f'[{chr(125)}]'


def js_template_escape(value):
    """Escape a plain string for safe inclusion in a JS template literal."""
    out = value.replace(chr(92), chr(92) * 2)
    out = out.replace(BT, chr(92) + BT)
    out = out.replace('${', chr(92) + '${')
    out = out.replace(chr(13), chr(92) + 'r')
    out = out.replace(chr(10), chr(92) + 'n')
    return out


def build_ru_literal(catalog, extra):
    """Serialize the ru catalog as a JS object literal: "key":`value`,..."""
    merged = dict(catalog)
    for k, v in extra.items():
        merged.setdefault(k, v)
    parts = []
    for k, v in merged.items():
        parts.append(f'"{k}":{qx(js_template_escape(v))}')
    return '{' + ','.join(parts) + '}'


# --------------------------------------------------------------------------
# @electron/asar CLI wrapper
# --------------------------------------------------------------------------

def asar_cli():
    exe = shutil.which('npx') or shutil.which('npx.cmd')
    if not exe:
        raise RuntimeError('npx not found on PATH; install Node.js from https://nodejs.org')
    return exe


def run_asar(args, cwd):
    cmd = [asar_cli(), '--yes', '@electron/asar'] + args
    proc = subprocess.run(cmd, cwd=cwd, shell=False,
                          capture_output=True, text=True, encoding='utf-8', errors='replace')
    if proc.returncode != 0:
        raise RuntimeError(f'asar {" ".join(args[:1])} failed: {proc.stderr.strip()[:500]}')
    return proc.stdout


def read_header(asar_path):
    """Parse the JSON manifest of an asar archive (direct access, no tree walk)."""
    with open(asar_path, 'rb') as f:
        head = f.read(16)
        json_len = struct.unpack_from('<I', head, 12)[0]
        header_size = struct.unpack_from('<I', head, 4)[0]
        raw = f.read(json_len).decode('utf-8')
        data_start = 8 + header_size
    header = json.loads(raw)
    return header, data_start


def read_entry_bytes(asar_path, header, data_start, *keys):
    """Read one archive entry addressed by explicit manifest keys."""
    node = header['files']
    for i, k in enumerate(keys):
        if i:
            node = node['files']
        node = node[k]
    offset = int(node['offset'], 10)
    size = node['size']
    if offset < 0 or size < 0 or size > 64 * 1024 * 1024:
        raise RuntimeError(f'implausible entry: offset={offset} size={size}')
    with open(asar_path, 'rb') as f:
        f.seek(data_start + offset)
        return f.read(size)

# --------------------------------------------------------------------------
# chunk patching
# --------------------------------------------------------------------------

RU_EXTRA_LABELS = {
    'settings.locale.ru': RU_LABEL,
    'sidebar.settings.locale.ru': RU_LABEL,
}


def patch_catalog_chunk(text, ru_literal):
    """Patch the IntlProvider chunk. Returns (patched_text, report dict)."""
    report = {}

    # 1. Add the ru display-name entries to BOTH existing dicts (zh and en),
    #    so the new dropdown item has a label in every UI language.
    label_entry = f',"settings.locale.ru":{qx(RU_LABEL)},"sidebar.settings.locale.ru":{qx(RU_LABEL)}'
    pattern = f'("settings\\.locale\\.en-US":{BT}[^{BT}]*{BT})'
    text, n = re.subn(pattern, lambda m: m.group(1) + label_entry, text)
    report['label entries added'] = n
    if n < 2:
        raise RuntimeError(f'expected 2 settings.locale.en-US occurrences, found {n}')

    # 2. Insert the ru catalog as a new variable, before the zh catalog variable.
    anchor = 'var p={'
    if anchor not in text:
        raise RuntimeError('catalog var anchor "var p={" not found')
    text = text.replace(anchor, f'var ruCat={ru_literal},p={{', 1)
    report['ru catalog inserted'] = len(ru_literal)

    # 3. Register ru in the locale map.
    text, n = re.subn(r'\{"zh-CN":(\w+),"en-US":(\w+)\}',
                      lambda m: f'{{"zh-CN":{m.group(1)},"en-US":{m.group(2)},"ru":ruCat}}',
                      text)
    report['locale map patched'] = n
    if n < 1:
        raise RuntimeError('locale map {"zh-CN":...,"en-US":...} not found')

    # 4. Allow ru in locale validators (e === `zh-CN` || e === `en-US`).
    text, n = re.subn(f'(?P<v>[\\w$]+)==={qx("zh-CN")}\\|\\|(?P=v)==={qx("en-US")}',
                      lambda m: m.group(0) + f'||{m.group("v")}==={qx("ru")}', text)
    report['validators patched'] = n
    if n < 1:
        raise RuntimeError('locale validator not found')

    # 5. System-locale resolver: navigator language starting with "ru" now maps to ru.
    text, n = re.subn(
        f'(?P<left>[\\w$.]+)\\.toLowerCase\\(\\)\\.startsWith\\({qx("zh")}\\)\\?{qx("zh-CN")}:{qx("en-US")}',
        lambda m: (f'{m.group("left")}.toLowerCase().startsWith({qx("zh")})?{qx("zh-CN")}:'
                   f'{m.group("left")}.toLowerCase().startsWith({qx("ru")})?{qx("ru")}:{qx("en-US")}'),
        text)
    report['system resolver patched'] = n
    if n < 1:
        raise RuntimeError('system locale resolver not found')

    # 6. Export the ru catalog for the main bundle.
    text, n = re.subn(r'export\{([^{}]+)\}',
                      lambda m: f'export{{{m.group(1)},ruCat as ru}}',
                      text, count=1)
    report['export patched'] = n
    if n < 1:
        raise RuntimeError('export statement not found')

    return text, report


def patch_main_chunk(text):
    """Patch the main renderer bundle. Returns (patched_text, report dict)."""
    report = {}

    # 1. Import the ru catalog exported by the IntlProvider chunk.
    text, n = re.subn(r'import\{([^{}]+)\}from"(\./IntlProvider-[^"]+\.js)"',
                      lambda m: f'import{{{m.group(1)},ru as rue}}from"{m.group(2)}"',
                      text, count=1)
    report['import patched'] = n
    if n < 1:
        raise RuntimeError('import from IntlProvider chunk not found')

    # 2. Error-screen dictionary getter: add a ru branch.
    text, n = re.subn(
        f'function (?P<f>\\w+)\\(e\\){OB}return\\((?P<g>\\w+)\\(\\)==={qx("en-US")}\\?(?P<en>\\w+):(?P<zh>\\w+)\\)\\[e\\]\\?\\?e{CB}',
        lambda m: (f'function {m.group("f")}(e){OB}return({m.group("g")}()==={qx("en-US")}?{m.group("en")}:'
                   f'{m.group("g")}()==={qx("ru")}?rue:{m.group("zh")})[e]??e{CB}'),
        text, count=1)
    report['error dict patched'] = n
    if n < 1:
        raise RuntimeError('error dictionary getter not found')

    # 3. Allow ru in all locale checks (preference validators, dropdown handlers).
    text, n = re.subn(f'(?P<v>[\\w$]+)==={qx("zh-CN")}\\|\\|(?P=v)==={qx("en-US")}',
                      lambda m: m.group(0) + f'||{m.group("v")}==={qx("ru")}', text)
    report['locale checks patched'] = n
    if n < 3:
        raise RuntimeError(f'expected >=3 locale checks, found {n}')

    # 4. System-locale resolver (same shape as in the catalog chunk).
    text, n = re.subn(
        f'(?P<left>[\\w$.]+)\\.toLowerCase\\(\\)\\.startsWith\\({qx("zh")}\\)\\?{qx("zh-CN")}:{qx("en-US")}',
        lambda m: (f'{m.group("left")}.toLowerCase().startsWith({qx("zh")})?{qx("zh-CN")}:'
                   f'{m.group("left")}.toLowerCase().startsWith({qx("ru")})?{qx("ru")}:{qx("en-US")}'),
        text)
    report['system resolver patched'] = n
    if n < 1:
        raise RuntimeError('system locale resolver not found')

    # 5. Language dropdown #1 (sidebar settings): add a "Русский" option.
    text, n = re.subn(
        f'\\(0,(?P<jsx>[\\w$]+\\.[\\w$]+)\\)\\((?P<cmp>[\\w$]+),{OB}value:{qx("en-US")},children:(?P<fmt>[\\w$]+)\\.formatMessage\\({OB}id:{qx("sidebar.settings.locale.en-US")}{CB}\\){CB}\\)',
        lambda m: (m.group(0) +
                   f',(0,{m.group("jsx")})({m.group("cmp")},{OB}value:{qx("ru")},children:'
                   f'{m.group("fmt")}.formatMessage({OB}id:{qx("sidebar.settings.locale.ru")}{CB}){CB})'),
        text, count=1)
    report['sidebar dropdown option added'] = n
    if n < 1:
        raise RuntimeError('sidebar language dropdown not found')

    # 6. Language dropdown #2 (settings page, with data-testid): add a "Русский" option.
    text, n = re.subn(
        f'\\(0,(?P<jsx>[\\w$]+\\.[\\w$]+)\\)\\((?P<cmp>[\\w$]+),{OB}value:{qx("en-US")},"data-testid":(?P<tid>[\\w$]+)\\((?P<tidarg>[\\w$]+),{qx("en-US")}\\),children:(?P<fmt>[\\w$]+)\\.formatMessage\\({OB}id:{qx("settings.locale.en-US")}{CB}\\){CB}\\)',
        lambda m: (m.group(0) +
                   f',(0,{m.group("jsx")})({m.group("cmp")},{OB}value:{qx("ru")},"data-testid":'
                   f'{m.group("tid")}({m.group("tidarg")},{qx("ru")}),children:'
                   f'{m.group("fmt")}.formatMessage({OB}id:{qx("settings.locale.ru")}{CB}){CB})'),
        text, count=1)
    report['settings dropdown option added'] = n
    if n < 1:
        raise RuntimeError('settings language dropdown not found')

    return text, report

# --------------------------------------------------------------------------
# installation discovery and top-level flow
# --------------------------------------------------------------------------

def find_asar(explicit):
    if explicit:
        return os.path.realpath(explicit)
    home = os.path.expanduser('~')
    candidates = [
        os.path.join(os.environ.get('LOCALAPPDATA', os.path.join(home, 'AppData', 'Local')),
                     'Programs', 'ZCode', 'resources', 'app.asar'),
        '/Applications/ZCode.app/Contents/Resources/app.asar',
        '/opt/ZCode/resources/app.asar',
        '/usr/lib/zcode/resources/app.asar',
    ]
    for c in candidates:
        if os.path.isfile(c):
            return os.path.realpath(c)
    raise RuntimeError('app.asar not found; pass --asar /path/to/app.asar')


def find_chunks_in_tree(extracted_dir):
    """Locate the two chunks inside the extracted tree by content."""
    assets = os.path.join(extracted_dir, 'out', 'renderer', 'assets')
    if not os.path.isdir(assets):
        raise RuntimeError('extracted tree lacks out/renderer/assets')
    catalog_name = None
    main_name = None
    for name in os.listdir(assets):
        if not name.endswith('.js'):
            continue
        if name.startswith('IntlProvider-'):
            catalog_name = name
            continue
        with io.open(os.path.join(assets, name), encoding='utf-8', errors='ignore') as f:
            text = f.read()
        if 'zcode-locale-preference' in text:
            main_name = name
        if catalog_name and main_name:
            break
    if not catalog_name:
        raise RuntimeError('IntlProvider chunk not found (is this a ZCode install?)')
    if not main_name:
        raise RuntimeError('main renderer bundle not found')
    return assets, catalog_name, main_name


def default_catalog_path():
    tool_dir = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.dirname(tool_dir)
    return os.path.join(repo_root, 'translations', 'ru-RU-catalog.json')


def main():
    ap = argparse.ArgumentParser(description='Apply Russian localization to ZCode')
    ap.add_argument('--asar', help='path to resources/app.asar (default: auto-detect)')
    ap.add_argument('--catalog', help='path to ru-RU-catalog.json (default: alongside this script)')
    ap.add_argument('--dry-run', action='store_true', help='patch in memory, write nothing')
    ap.add_argument('--keep-workdir', action='store_true', help='keep the temp extraction dir')
    args = ap.parse_args()

    asar_path = find_asar(args.asar)
    resources_dir = os.path.dirname(asar_path)
    print(f'ZCode archive: {asar_path}')

    catalog_path = args.catalog or default_catalog_path()
    if not os.path.isfile(catalog_path):
        raise RuntimeError(f'catalog not found: {catalog_path}')
    with io.open(catalog_path, encoding='utf-8') as f:
        ru_catalog = json.load(f)
    print(f'Russian catalog: {catalog_path} ({len(ru_catalog)} strings)')

    stamp = time.strftime('%Y%m%d-%H%M%S')
    workdir = os.path.join(resources_dir, f'zcode-ru-work-{stamp}')
    extracted = os.path.join(workdir, 'tree')
    os.makedirs(extracted, exist_ok=True)

    print('Extracting archive with @electron/asar (first run may download the tool)...')
    run_asar(['extract', asar_path, extracted], cwd=resources_dir)

    # Unpacked entries (native binaries) are not part of the archive, so the
    # extraction misses them; copy them from the sidecar into the tree so the
    # pack step can mark them unpacked again.
    sidecar_root = os.path.join(resources_dir, 'app.asar.unpacked')
    if os.path.isdir(sidecar_root):
        for dirpath, dirnames, filenames in os.walk(sidecar_root):
            rel = os.path.relpath(dirpath, sidecar_root)
            target_dir = os.path.join(extracted, rel) if rel != chr(46) else extracted
            os.makedirs(target_dir, exist_ok=True)
            for fn in filenames:
                shutil.copy2(os.path.join(dirpath, fn), os.path.join(target_dir, fn))

    assets, catalog_name, main_name = find_chunks_in_tree(extracted)
    print(f'  catalog chunk : {catalog_name}')
    print(f'  main bundle   : {main_name}')

    with io.open(os.path.join(assets, catalog_name), encoding='utf-8') as f:
        cat_text = f.read()
    with io.open(os.path.join(assets, main_name), encoding='utf-8') as f:
        main_text = f.read()

    if '"ru":ruCat' in cat_text:
        print('Already patched — nothing to do.')
        shutil.rmtree(workdir, ignore_errors=True)
        return 0

    ru_literal = build_ru_literal(ru_catalog, RU_EXTRA_LABELS)
    print('Patching catalog chunk...')
    new_cat, rep1 = patch_catalog_chunk(cat_text, ru_literal)
    for k, v in rep1.items():
        print(f'  {k}: {v}')
    print('Patching main bundle...')
    new_main, rep2 = patch_main_chunk(main_text)
    for k, v in rep2.items():
        print(f'  {k}: {v}')

    if args.dry_run:
        shutil.rmtree(workdir, ignore_errors=True)
        print('Dry run OK — no files were modified.')
        return 0

    with io.open(os.path.join(assets, catalog_name), 'w', encoding='utf-8', newline='') as f:
        f.write(new_cat)
    with io.open(os.path.join(assets, main_name), 'w', encoding='utf-8', newline='') as f:
        f.write(new_main)

    packed = os.path.join(workdir, 'app.asar.new')
    print('Packing archive with @electron/asar (native binaries stay unpacked)...')
    run_asar(['pack', extracted, packed,
              '--unpack', '**/*.{node,dll,exe}'], cwd=resources_dir)

    print('Verifying result...')
    header_old, data_old = read_header(asar_path)
    header_new, data_new = read_header(packed)
    problems = []

    # The unpacked set must match exactly: compare the sidecar file listings.
    # (Directory-level "unpacked" flags in the original header are packing
    # metadata; runtime lookup only consults per-file flags, which the pack
    # step reproduces from the same binaries.)
    sidecar_old = os.path.join(resources_dir, 'app.asar.unpacked')
    sidecar_new = packed + '.unpacked'

    def sidecar_files(root):
        found = []
        if os.path.isdir(root):
            for dirpath, _dirnames, filenames in os.walk(root):
                for fn in filenames:
                    found.append(os.path.relpath(os.path.join(dirpath, fn), root).replace(os.sep, '/'))
        return sorted(found)

    if sidecar_files(sidecar_old) != sidecar_files(sidecar_new):
        problems.append('unpacked sidecar file lists differ')

    pkg_old = read_entry_bytes(asar_path, header_old, data_old, 'package.json')
    pkg_new = read_entry_bytes(packed, header_new, data_new, 'package.json')
    if pkg_old != pkg_new:
        problems.append('package.json differs after rebuild')

    cat_new = read_entry_bytes(packed, header_new, data_new,
                               'out', 'renderer', 'assets', catalog_name).decode('utf-8', 'ignore')
    main_new = read_entry_bytes(packed, header_new, data_new,
                                'out', 'renderer', 'assets', main_name).decode('utf-8', 'ignore')
    for marker in ('"ru":ruCat', 'ruCat as ru', '"settings.locale.ru"'):
        if marker not in cat_new:
            problems.append(f'marker {marker!r} missing in catalog chunk')
    for marker in ('ru as rue', '?rue:', qx('sidebar.settings.locale.ru')):
        if marker not in main_new:
            problems.append(f'marker {marker!r} missing in main bundle')
    if problems:
        raise RuntimeError('verification failed: ' + '; '.join(problems))

    backup = f'{asar_path}.bak-{stamp}'
    print(f'Creating backup: {backup}')
    shutil.copy2(asar_path, backup)

    try:
        os.replace(packed, asar_path)
    except PermissionError:
        staged = os.path.join(resources_dir, 'app.asar.new-ru')
        shutil.copy2(packed, staged)
        shutil.rmtree(workdir, ignore_errors=True)
        print()
        print('ZCode is running and locks app.asar, so the file was not replaced.')
        print(f'The patched archive is staged at: {staged}')
        print('To finish, either close ZCode and re-run this tool, or run:')
        print(f'  tool{os.sep}swap_after_close.cmd "{staged}"')
        print('It waits for ZCode to exit, swaps the file, and you can start ZCode again.')
        return 2

    # resources/app.asar.unpacked keeps the original native binaries; the pack
    # step reproduced the same unpacked set from the tree, so no sidecar changes.

    if args.keep_workdir:
        print(f'Work dir kept: {workdir}')
    else:
        shutil.rmtree(workdir, ignore_errors=True)

    print(f'Done. Patched archive written to {asar_path}')
    print('Restart ZCode, then open Settings and pick "Русский".')
    print(f'To revert: replace app.asar with the backup {os.path.basename(backup)}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
