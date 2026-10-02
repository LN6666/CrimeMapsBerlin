"""Operating tunnel members retain their literal native tram relation mode."""
import copy
import pytest
from shapely.geometry import LineString,box,mapping
from crimemapsberlin.city_transit_index import route_object

def fixture():
    relation={"id":7,"tags":{"type":"route","route":"tram","ref":"7","name":"Linie 7"},
              "members":[{"type":"w","ref":1,"role":""},{"type":"w","ref":2,"role":""}]}
    ways={1:{"tags":{"railway":"tram"},"geometry":mapping(LineString([(1,1),(2,1)]))},
          2:{"tags":{"railway":"subway","tunnel":"yes","layer":"-2"},
             "geometry":mapping(LineString([(2,1),(3,1)]))}}
    return relation,ways

def test_operating_tram_tunnel_preserves_native_mode_and_members():
    relation,ways=fixture();before=copy.deepcopy((relation,ways))
    result=route_object(relation,ways,box(0,0,4,4))
    assert result["tags"]["route"]=="tram"
    assert result["transit_source_proof"]["member_way_ids"]==[1,2]
    assert (relation,ways)==before

@pytest.mark.parametrize("change",[
    {"tunnel":"no"},{"railway":"construction"},
    {"construction:railway":"subway"},{"disused:railway":"subway"},
    {"proposed:railway":"subway"},{"abandoned:railway":"subway"},
])
def test_hybrid_mode_does_not_accept_surface_or_inactive_paths(change):
    relation,ways=fixture();ways[2]["tags"].update(change)
    with pytest.raises(ValueError,match="inactive or incompatible"):
        route_object(relation,ways,box(0,0,4,4))
