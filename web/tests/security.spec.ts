import {test,expect} from "@playwright/test";
import {assertManifestPaths,safeLocalDataPath,safeExternalURL} from "../src/safety/security";
const manifest={schema_version:2,generation:"abcdef0123456789-20261003T000000",months:{"2026-10":{}},tile_index:{pois:["park/335_2100"],roads:["335_2100"]},tile_size:[0.04,0.025],categories:["gewalt"]};
test("manifest route values cannot escape city data and tile size is finite",()=>{
  expect(()=>assertManifestPaths(manifest,"/crimemaps-Berlin/safety")).not.toThrow();
  for(const value of [{months:{"../secret":{}}},{months:{"2026-13":{}}},{tile_size:[0,1]},{tile_size:[NaN,1]},{tile_index:{pois:["../../secret"],roads:[]}}])
    expect(()=>assertManifestPaths({...manifest,...value},"/safety")).toThrow();
});
test("data paths reject encoded traversal, scheme-relative URLs and secret query strings",()=>{
  for(const value of ["//evil.example/data","/safety/%2e%2e/data","/safety/../data","/safety/data?token=x","/safety//data"])
    expect(()=>safeLocalDataPath(value)).toThrow();
});
test("external links reject executable schemes, userinfo, controls and nonstandard ports",()=>{
  for(const value of ["javascript:alert(1)","http://example.org","https://user:password@example.org","https://example.org:8443","https://example.org/\nx"])
    expect(safeExternalURL(value)).toBeNull();
  expect(safeExternalURL("https://www.berlin.de/polizei/")).toBe("https://www.berlin.de/polizei/");
});
