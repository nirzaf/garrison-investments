import json
from pathlib import Path

data = json.loads(Path('graphify-out/graph.json').read_text())
nodes = {n['id']: n for n in data['nodes']}
links = data.get('links', [])

# Find the specific surprising connections
targets = [
    ("str", "Settings"),
    ("AsyncClient", "Settings"),
    ("test_unhandled_exception_email_respects_disabled_config()", "FastAPI"),
    ("Namespace", "Request"),
    ("int", "Request"),
]

for src_label, tgt_label in targets:
    src_ids = [nid for nid, n in nodes.items() if n.get('label') == src_label]
    tgt_ids = [nid for nid, n in nodes.items() if n.get('label') == tgt_label]
    
    print(f"\n=== {src_label} -> {tgt_label} ===")
    print(f"  Source nodes matching '{src_label}': {len(src_ids)}")
    for sid in src_ids[:5]:
        n = nodes[sid]
        print(f"    {sid}: source_file={n.get('source_file','?')}, file_type={n.get('file_type','?')}")
    print(f"  Target nodes matching '{tgt_label}': {len(tgt_ids)}")
    for tid in tgt_ids[:5]:
        n = nodes[tid]
        print(f"    {tid}: source_file={n.get('source_file','?')}, file_type={n.get('file_type','?')}")
    
    # Find edges between them
    found = []
    for link in links:
        s = link.get('source', '')
        t = link.get('target', '')
        s_label = nodes.get(s, {}).get('label', '')
        t_label = nodes.get(t, {}).get('label', '')
        if s_label == src_label and t_label == tgt_label:
            found.append(link)
        elif s_label == tgt_label and t_label == src_label:
            found.append(link)
    
    print(f"  Edges found: {len(found)}")
    for e in found[:3]:
        s_name = nodes.get(e['source'], {}).get('label', e['source'])
        t_name = nodes.get(e['target'], {}).get('label', e['target'])
        print(f"    {s_name} --{e.get('relation','?')}[{e.get('confidence','?')}]--> {t_name}")
        print(f"      source_file={e.get('source_file','?')}")
