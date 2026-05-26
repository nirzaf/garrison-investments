import json

g = json.load(open("graphify-out/graph.json"))
nodes = g["nodes"]
links = g["links"]

ex = sum(1 for l in links if l.get("confidence") == "EXTRACTED")
inf = sum(1 for l in links if l.get("confidence") == "INFERRED")

print(f"Nodes: {len(nodes)}")
print(f"Edges: {len(links)}")
print(f"File size: {4693957} bytes")
print(f"EXTRACTED: {ex} ({ex*100//len(links)}%)")
print(f"INFERRED: {inf} ({inf*100//len(links)}%)")

coms = {}
for n in nodes:
    c = n.get("community", "none")
    coms[c] = coms.get(c, 0) + 1
sizes = sorted(coms.values(), reverse=True)
print(f"Communities: {len(coms)}")
print(f"Largest community: {max(coms.values())} nodes")
print(f"Median community: {sizes[len(sizes)//2]} nodes")
print(f"Avg community: {sum(sizes)/len(sizes):.1f} nodes")

types = {}
for n in nodes:
    t = n.get("file_type", "?")
    types[t] = types.get(t, 0) + 1
print(f"Types: {types}")

rels = {}
for l in links:
    r = l.get("relation", "?")
    rels[r] = rels.get(r, 0) + 1
print(f"\nTop 10 relationships:")
for r, c in sorted(rels.items(), key=lambda x: -x[1])[:10]:
    print(f"  {r}: {c}")

conn = {}
for l in links:
    conn[l["source"]] = conn.get(l["source"], 0) + 1
    conn[l["target"]] = conn.get(l["target"], 0) + 1
id2l = {n["id"]: n.get("label", n["id"]) for n in nodes}

print(f"\nGod nodes:")
for nid, cnt in sorted(conn.items(), key=lambda x: -x[1])[:12]:
    print(f"  {id2l.get(nid, nid)}: {cnt}")
