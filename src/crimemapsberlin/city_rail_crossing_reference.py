"""Original road/rail vertices identify a crossing site, never an event extent."""
from __future__ import annotations

import copy,itertools,re
from shapely.geometry import MultiPoint,mapping,shape
from shapely.ops import transform,unary_union
from .city_geometry_index import _digest
from .poi_cities import POI_CITY_SPECS
from .spatial import metric_transforms

METHOD = "osm_rail_crossing_area_reference"
PROOF = "native_crossing_way_source_proof"
HEX = re.compile(r"[0-9a-f]{64}")


def enrich_crossing_way(row: dict, *, original: dict, source_cache_sha256: str,
                        source_pbf_sha256: str) -> dict:
    """Attach original grade/vertices; leave indexed tags, aliases and geometry exact."""
    source = {"id":row["id"],"tags":original["tags"],"geometry":original["geometry"]}
    if "node_ids" in original:source["node_ids"]=original["node_ids"]
    result=copy.deepcopy(row)
    if PROOF in result:raise ValueError("crossing source proof is already present")
    result[PROOF]={"schema_version":1,"source_pbf_sha256":source_pbf_sha256,
        "source_cache_sha256":source_cache_sha256,"source_way":copy.deepcopy(source),
        "source_way_sha256":_digest(source),"original_geometry_preserved":True}
    if not valid_crossing_way(result,source_pbf_sha256=source_pbf_sha256):
        raise ValueError("crossing source geometry, grade or member digest is inconsistent")
    return result


def valid_crossing_way(row: dict, *, source_pbf_sha256: str | None = None) -> bool:
    proof=row.get(PROOF)
    if not isinstance(proof,dict) or set(proof)!={"schema_version","source_pbf_sha256",
        "source_cache_sha256","source_way","source_way_sha256","original_geometry_preserved"}:return False
    original=proof["source_way"]
    if (proof["schema_version"]!=1 or proof["original_geometry_preserved"] is not True
            or not all(isinstance(proof[k],str) and HEX.fullmatch(proof[k]) for k in ["source_pbf_sha256","source_cache_sha256"])
            or source_pbf_sha256 is not None and proof["source_pbf_sha256"]!=source_pbf_sha256
            or not isinstance(original,dict) or not {"id","tags","geometry"}<=original.keys()
            or original.keys()-{"id","tags","geometry","node_ids"}
            or proof["source_way_sha256"]!=_digest(original)
            or original["id"]!=row.get("id") or not re.fullmatch(r"osm/way/[1-9][0-9]*",original["id"])
            or original["geometry"]!=row.get("geometry") or original["geometry"].get("type")!="LineString"
            or not isinstance(original["tags"],dict)
            or not all(isinstance(k,str) and isinstance(v,str) for k,v in original["tags"].items())
            or any(original["tags"].get(k)!=v for k,v in row.get("tags",{}).items())):return False
    try:
        geometry=shape(original["geometry"])
        if geometry.is_empty or not geometry.is_valid:return False
    except (ValueError,TypeError,KeyError):return False
    if "node_ids" in original:
        nodes=original["node_ids"]
        if not isinstance(nodes,list) or len(nodes)!=len(original["geometry"]["coordinates"]) or any(type(n) is not int or n<=0 for n in nodes):return False
    member=row.get("transit_member_source_proof")
    if member and member.get("source_way_digest")!=_digest({"tags":original["tags"],"geometry":original["geometry"]}):return False
    return True


def derive_crossing_reference(decision: dict, request: dict, objects: dict, border,
                              city: str, *, source_transit_contexts: list,
                              valid_carrier) -> dict:
    if (request.get("precision")!="area" or request.get("geometry_task")!="checked_area_geometry_required"
            or request.get("coordinates") is not None or request.get("transit_route") is not None
            or request.get("transit_review",{}).get("status")!="source_backed_context"):
        raise ValueError("rail crossing reference needs source-backed stationary area context")
    groups=decision["osm_object_groups"]
    if len(groups)!=4 or any(not group for group in groups):
        raise ValueError("rail crossing reference needs two named roads, crossing rail members and source carriers")
    try:roads=[[objects[i] for i in g] for g in groups[:2]];rails=[objects[i] for i in groups[2]];carriers=[objects[i] for i in groups[3]]
    except KeyError as exc:raise ValueError("rail crossing object is absent from the checked index") from exc
    names=[]
    for group in roads:
        road_names={r.get("tags",{}).get("name") for r in group}
        if (len(road_names)!=1 or not next(iter(road_names)) or any("road" not in r.get("roles",[]) or r.get("geometry",{}).get("type")!="LineString" for r in group)):
            raise ValueError("rail crossing needs two distinct named road identities")
        names.append(next(iter(road_names)))
    if names[0]==names[1]:raise ValueError("rail crossing road identities are identical")
    carrier_lines={r.get("tags",{}).get("ref") for r in carriers}
    if len(carrier_lines)!=1 or len(carriers)>2:raise ValueError("rail crossing needs the checked carrier family")
    line=next(iter(carrier_lines))
    if not any(c.get("mode")=="subway" and c.get("line")==line and c.get("extent")=="source_segment" for c in source_transit_contexts):
        raise ValueError("rail crossing carrier lacks a current linked source segment judgment")
    if any(not valid_carrier(r,line,"subway") for r in carriers):raise ValueError("rail crossing carrier proof is incomplete")
    for rail in rails:
        proof=rail.get("transit_member_source_proof",{})
        if (rail.get("tags",{}).get("railway") not in {"light_rail","subway"}
                or not any(m.get("line")==line and m.get("mode")=="subway"
                    and any(c["id"]==f'osm/relation/{m.get("relation_id")}' and proof.get("way_id") in c["transit_source_proof"]["member_way_ids"] for c in carriers)
                    for m in proof.get("memberships",[]))):raise ValueError("rail crossing member is not in its checked source carrier")
    def original_vertices(row):
        if not valid_crossing_way(row):raise ValueError("crossing vertex needs its original source way proof")
        tags=row[PROOF]["source_way"]["tags"]
        if any(tags.get(k,d)!=d for k,d in [("layer","0"),("level","0"),("bridge","no"),("tunnel","no")]):
            raise ValueError("crossing members have unverified or incompatible grade")
        return {tuple(p) for p in row["geometry"]["coordinates"]}
    def original_hits(left,right):
        hit=shape(left["geometry"]).intersection(shape(right["geometry"]))
        if hit.is_empty:return []
        if hit.geom_type not in {"Point","MultiPoint"}:raise ValueError("crossing is not a finite original vertex set")
        points=[hit] if hit.geom_type=="Point" else list(hit.geoms)
        common=original_vertices(left)&original_vertices(right)
        if any(tuple(p.coords[0]) not in common for p in points):raise ValueError("crossing would invent a planar intersection vertex")
        return points
    junction=[p for left,right in itertools.product(*roads) for p in original_hits(left,right)]
    if not junction:raise ValueError("named roads have no original junction")
    crossings=[]
    for rail in rails:
        hits=[p for road in itertools.chain.from_iterable(roads) for p in original_hits(rail,road)]
        if not hits:raise ValueError("selected rail member has no original road crossing")
        crossings.extend(hits)
    all_points=unary_union(junction+crossings)
    to_metric,_=metric_transforms(POI_CITY_SPECS[city].epsg)
    points=[all_points] if all_points.geom_type=="Point" else list(all_points.geoms)
    metric=[transform(to_metric,p) for p in points]
    if max((a.distance(b) for a,b in itertools.combinations(metric,2)),default=0)>150:
        raise ValueError("native road/rail candidates do not form a local crossing site")
    if not border.covers(all_points):raise ValueError("crossing reference lies outside the municipality")
    geojson=mapping(all_points);ids=[i for group in groups for i in group]
    return {"type":all_points.geom_type,"geometry":geojson,"geometry_sha256":_digest(geojson),
        "source_object_ids":ids,"source_object_groups":groups,"geometry_usage":"source_junction_reference_only",
        "actual_event_position_known":False,"actual_event_extent_known":False,
        "rail_crossing_reference":{"source_line":line,"source_mode":"subway","carrier_object_ids":groups[3],
            "named_road_junction_candidates":mapping(unary_union(junction)),
            "original_road_rail_crossing_candidates":mapping(unary_union(crossings)),
            "original_grade_checked":"ground","actual_transit_extent_known":False,
            "event_day_alignment_proven":False}}
