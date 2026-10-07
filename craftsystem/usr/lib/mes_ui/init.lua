-- Entry: require("mes_ui").run{tab="stock"} opens the production UI.
local M={}
function M.run(opts) return require("mes_ui.core").run(opts) end
return M
