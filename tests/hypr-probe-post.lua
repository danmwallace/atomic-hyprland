-- Test-only, loaded last by tests/image-smoke.sh: every key recorded by
-- hypr-probe-pre.lua must be one this Hyprland knows.
local unknown = 0
for _, key in ipairs(__probe_keys) do
  local _, err = hl.get_config(key)
  if err ~= nil then
    print("PROBE unknown config key: " .. key .. " (" .. tostring(err) .. ")")
    unknown = unknown + 1
  end
end
if unknown == 0 then
  print("PROBE config keys ok: " .. #__probe_keys)
end
