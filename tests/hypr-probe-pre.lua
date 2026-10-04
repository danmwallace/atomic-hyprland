-- Test-only shim, loaded first by tests/image-smoke.sh. Wraps hl.config so every
-- dotted key the config sets is recorded; hypr-probe-post.lua checks each one
-- with hl.get_config, because --verify-config silently ignores unknown keys.
__probe_keys = {}
local orig_config = hl.config
local function is_leaf(v)
  if type(v) ~= "table" then return true end
  if v.colors ~= nil or v[1] ~= nil then return true end   -- gradient / array value
  return false
end
local function walk(tbl, prefix)
  for k, v in pairs(tbl) do
    local key = (prefix == "") and tostring(k) or (prefix .. "." .. tostring(k))
    if is_leaf(v) then table.insert(__probe_keys, key) else walk(v, key) end
  end
end
hl.config = function(t)
  walk(t, "")
  return orig_config(t)
end
