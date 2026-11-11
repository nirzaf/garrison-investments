import json, sys
from graphify.build import build_from_json
from graphify.cluster import score_all
from graphify.analyze import god_nodes, surprising_connections, suggest_questions
from graphify.report import generate
from pathlib import Path

data = json.loads(Path('graphify-out/graph.json').read_text())
G = build_from_json({'nodes': data['nodes'], 'edges': data.get('links', []), 'hyperedges': []})

# Analyze communities from stored graph data
communities = {}
for n in data['nodes']:
    cid = n.get('community', 0)
    communities.setdefault(cid, []).append(n['id'])

# Label communities based on node content
community_labels = {}
for cid, nodes in communities.items():
    labels_seen = {}
    for nid in nodes[:30]:
        nd = next((n for n in data['nodes'] if n['id'] == nid), None)
        if nd:
            label = nd.get('label', nd.get('id', ''))
            ft = nd.get('file_type', '')
            key = (label, ft)
            labels_seen[key] = labels_seen.get(key, 0) + 1
    
    top = sorted(labels_seen.items(), key=lambda x: -x[1])[:5]
    top_labels = [f'{label}({ft})' for (label, ft), cnt in top[:3]]
    community_labels[cid] = f'Community {cid}: {", ".join(top_labels)}'

# Save labels
path_labels = Path('.graphify_labels.json')
path_labels.write_text(json.dumps({str(k): v for k, v in community_labels.items()}, indent=2))
print(f'Labeled {len(community_labels)} communities')
for cid in sorted(community_labels.keys()):
    print(f'  {cid}: {community_labels[cid]}')
