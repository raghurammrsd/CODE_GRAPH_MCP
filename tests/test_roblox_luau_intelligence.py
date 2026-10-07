from __future__ import annotations

import json
import time
from pathlib import Path

from typer.testing import CliRunner

from codegraph.cli import app
from codegraph.config import Settings
from codegraph.context import get_context
from codegraph.graph.traversal import analyze_impact, trace_call
from codegraph.indexing import Indexer
from codegraph.interrogation import (
    get_callees,
    get_callers,
    get_file,
    get_references,
    resolve_symbol,
    trace_path,
)
from codegraph.roblox import (
    RojoProject,
    list_roblox_modules,
    list_roblox_remotes,
    list_roblox_routes,
)


def _create_roblox_repo(root: Path) -> Path:
    """Create a realistic Roblox + Rojo + Knit + Flamework + DataStore repository."""
    default_project = {
        "name": "RobloxGame",
        "tree": {
            "$className": "DataModel",
            "ReplicatedStorage": {
                "$className": "ReplicatedStorage",
                "Shared": {"$path": "src/shared"},
                "Packages": {"$path": "Packages"},
                "Remotes": {"$path": "src/remotes"},
            },
            "ServerScriptService": {
                "$className": "ServerScriptService",
                "Server": {"$path": "src/server"},
            },
            "StarterPlayer": {
                "$className": "StarterPlayer",
                "StarterPlayerScripts": {
                    "$className": "StarterPlayerScripts",
                    "Client": {"$path": "src/client"},
                },
            },
        },
    }
    (root / "default.project.json").write_text(json.dumps(default_project, indent=2), encoding="utf-8")

    # Packages/Knit/init.luau
    knit_dir = root / "Packages" / "Knit"
    knit_dir.mkdir(parents=True, exist_ok=True)
    (knit_dir / "init.luau").write_text(
        """--!strict
export type ServiceDef = {
    Name: string,
    Client: { [string]: any }?,
}

local Knit = {}

function Knit.CreateService(def: ServiceDef)
    return def
end

function Knit.GetService(name: string)
    return { Name = name }
end

return table.freeze(Knit)
""",
        encoding="utf-8",
    )

    # src/shared/Types.luau (Luau types, exported types, local/global functions, table.freeze)
    shared_dir = root / "src" / "shared"
    shared_dir.mkdir(parents=True, exist_ok=True)
    (shared_dir / "Types.luau").write_text(
        """--!strict
type InternalState = {
    version: number,
}

export type ItemConfig = {
    id: string,
    price: number,
}

local Types = {}

local function validatePrice(price: number): boolean
    return price >= 0
end

function GlobalFormatItem(id: string): string
    return "item:" .. id
end

function Types.IsValidItem(item: ItemConfig): boolean
    return validatePrice(item.price)
end

Types.FormatPrice = function(price: number): string
    return tostring(price)
end

return table.freeze(Types)
""",
        encoding="utf-8",
    )

    # src/shared/ProfileService.luau
    (shared_dir / "ProfileService.luau").write_text(
        """local ProfileService = {}

function ProfileService.GetProfileStore(storeName: string, template: any)
    local store = {}
    function store:LoadProfileAsync(key: string)
        return { Data = template }
    end
    function store:Save()
        return true
    end
    return store
end

return ProfileService
""",
        encoding="utf-8",
    )

    # src/server/Services/InventoryService.luau
    services_dir = root / "src" / "server" / "Services"
    services_dir.mkdir(parents=True, exist_ok=True)
    (services_dir / "InventoryService.luau").write_text(
        """--!strict
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local DataStoreService = game:GetService("DataStoreService")
local Packages = ReplicatedStorage.Packages
local Knit = require(Packages.Knit)
local Types = require(ReplicatedStorage.Shared.Types)
local ProfileService = require(ReplicatedStorage.Shared.ProfileService)

local Remotes = ReplicatedStorage:WaitForChild("Remotes")
local InventoryRemote = Remotes:WaitForChild("Inventory")
local PurchaseFunc = Remotes:WaitForChild("PurchaseItem")

local PlayerDataStore = DataStoreService:GetDataStore("PlayerInventory_v1")
local ProfileStore = ProfileService.GetProfileStore("PlayerProfiles_v1", {})

local InventoryService = Knit.CreateService({
    Name = "InventoryService",
    Client = {},
})

function InventoryService:HandleInventoryRequest(player: Player, itemId: string)
    local current = PlayerDataStore:GetAsync( tostring(player.UserId) )
    PlayerDataStore:SetAsync(tostring(player.UserId), itemId)
    PlayerDataStore:UpdateAsync(tostring(player.UserId), function(old)
        return old
    end)
    local profile = ProfileStore:LoadProfileAsync("Player_" .. tostring(player.UserId))
    return Types.IsValidItem({ id = itemId, price = 10 })
end

function InventoryService:KnitInit()
    InventoryRemote.OnServerEvent:Connect(function(player, itemId)
        InventoryService:HandleInventoryRequest(player, itemId)
    end)
    PurchaseFunc.OnServerInvoke = function(player, itemId)
        return InventoryService:HandleInventoryRequest(player, itemId)
    end
end

return InventoryService
""",
        encoding="utf-8",
    )

    # src/server/Services/RewardService.luau (relative require via script.Parent + Knit.GetService)
    (services_dir / "RewardService.luau").write_text(
        """local ReplicatedStorage = game:GetService("ReplicatedStorage")
local Knit = require(ReplicatedStorage.Packages.Knit)
local InventoryServiceModule = require(script.Parent.InventoryService)

local RewardService = Knit.CreateService({
    Name = "RewardService",
})

function RewardService:GrantStarterPack(player: Player)
    local inv = Knit.GetService("InventoryService")
    return inv
end

return RewardService
""",
        encoding="utf-8",
    )

    # src/client/Controllers/ClientController.luau
    controllers_dir = root / "src" / "client" / "Controllers"
    controllers_dir.mkdir(parents=True, exist_ok=True)
    (controllers_dir / "ClientController.luau").write_text(
        """--!strict
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local Remotes = ReplicatedStorage:WaitForChild("Remotes")
local InventoryRemote = Remotes:WaitForChild("Inventory")
local PurchaseFunc = Remotes:WaitForChild("PurchaseItem")

local ClientController = {}

function ClientController:RequestInventoryUpdate(itemId: string)
    InventoryRemote:FireServer(itemId)
    local result = PurchaseFunc:InvokeServer(itemId)
    return result
end

return ClientController
""",
        encoding="utf-8",
    )

    # src/client/Controllers/FlameworkController.ts (roblox-ts / Flamework)
    (controllers_dir / "FlameworkController.ts").write_text(
        """import { Controller, Service, Dependency } from "@flamework/core";

@Service()
export class CombatService {
    public attack(): void {}
}

@Controller()
export class CombatController {
    private combat = Dependency<CombatService>();

    public onStart(): void {
        this.combat.attack();
    }
}
""",
        encoding="utf-8",
    )

    return root


def test_roblox_17_positive_capabilities_and_acceptance_scenario(tmp_path: Path) -> None:
    """Verify all 17 positive capabilities + the end-to-end acceptance scenario."""
    repo = _create_roblox_repo(tmp_path.resolve())
    indexer = Indexer(repository=repo, settings=Settings())
    summary = indexer.index()
    assert summary["indexed"] >= 6

    with indexer.session() as con:
        # 1. Local & global function parsing
        local_fn = resolve_symbol(con, repo, "validatePrice")
        assert local_fn["status"] == "ok"
        assert local_fn["symbol"]["name"] == "validatePrice"
        assert local_fn["symbol"]["kind"] == "function"

        global_fn = resolve_symbol(con, repo, "GlobalFormatItem")
        assert global_fn["status"] == "ok"
        assert global_fn["symbol"]["kind"] == "function"

        # 2. Method syntax `function Service:Init()` and `function Types.IsValidItem()`
        colon_method = resolve_symbol(con, repo, "InventoryService.HandleInventoryRequest")
        assert colon_method["status"] == "ok"
        assert colon_method["symbol"]["kind"] == "method"

        dot_method = resolve_symbol(con, repo, "Types.IsValidItem")
        assert dot_method["status"] == "ok"
        assert dot_method["symbol"]["kind"] == "method"

        # 3. Assignment method `Types.FormatPrice = function(...)`
        assign_method = resolve_symbol(con, repo, "Types.FormatPrice")
        assert assign_method["status"] == "ok"
        assert assign_method["symbol"]["kind"] == "method"

        # 4. Module table return & 5. table.freeze(Module)
        types_table = resolve_symbol(con, repo, "Types")
        assert types_table["status"] == "ok"

        # 6. Luau type declarations (`type InternalState = ...`, `export type ItemConfig = ...`)
        internal_type = resolve_symbol(con, repo, "InternalState")
        assert internal_type["status"] == "ok"
        assert internal_type["symbol"]["kind"] == "type"

        export_type = resolve_symbol(con, repo, "ItemConfig")
        assert export_type["status"] == "ok"
        assert export_type["symbol"]["kind"] == "type"

        # 7. Rojo project mapping (`default.project.json`)
        rojo = RojoProject.load(repo)
        assert rojo is not None
        assert rojo.is_valid
        known_files = {
            str(r["path"]) for r in con.execute("SELECT path FROM files").fetchall()
        }
        resolved_knit, ev_knit = rojo.resolve_virtual_to_file(
            "ReplicatedStorage.Packages.Knit", known_files
        )
        assert resolved_knit == "Packages/Knit/init.luau"
        assert ev_knit == "ROJO_VERIFIED"

        # 8. `require(script.Parent...)` and `require(ReplicatedStorage.Packages.Knit)` -> REQUIRES_MODULE
        mods = list_roblox_modules(con, repo)
        assert mods["rojo_configured"] is True
        all_req_edges = mods["requires"]
        assert any(
            "Knit" in r["target"] and r["evidence_class"] == "ROJO_VERIFIED"
            for r in all_req_edges
        )
        assert any(
            "InventoryService" in r["target"] and r["evidence_class"] in {"AST_VERIFIED", "ROJO_VERIFIED"}
            for r in all_req_edges
        )

        # 9 & 10. RemoteEvent:FireServer -> OnServerEvent:Connect & RemoteFunction:InvokeServer -> OnServerInvoke
        remotes_res = list_roblox_remotes(con, repo)
        remotes_by_name = {r["remote"]: r for r in remotes_res["remotes"]}
        assert "ReplicatedStorage.Remotes.Inventory" in remotes_by_name
        inv_remote = remotes_by_name["ReplicatedStorage.Remotes.Inventory"]
        assert inv_remote["evidence_class"] == "ROJO_VERIFIED"
        assert any("ClientController" in c["symbol"] for c in inv_remote["client_dispatchers"])
        assert any("InventoryService" in s["symbol"] for s in inv_remote["server_handlers"])

        assert "ReplicatedStorage.Remotes.PurchaseItem" in remotes_by_name
        pur_remote = remotes_by_name["ReplicatedStorage.Remotes.PurchaseItem"]
        assert any("ClientController" in c["symbol"] for c in pur_remote["client_dispatchers"])
        assert any("InventoryService" in s["symbol"] for s in pur_remote["server_handlers"])

        # 11 & 12. Knit.CreateService -> PROVIDES_SERVICE & Knit.GetService -> GETS_SERVICE
        routes_res = list_roblox_routes(con, repo)
        services = routes_res["services"]
        assert any(
            s["relationship"] == "PROVIDES_SERVICE"
            and "InventoryService" in s["service"]
            and s["evidence_class"] == "FRAMEWORK_VERIFIED"
            for s in services
        )
        assert any(
            s["relationship"] == "GETS_SERVICE"
            and "InventoryService" in s["service"]
            and s["evidence_class"] == "FRAMEWORK_VERIFIED"
            for s in services
        )

        # 13 & 14. DataStoreService:GetDataStore + GetAsync/SetAsync/UpdateAsync & ProfileService
        persistence = routes_res["persistence"]
        assert any(
            p["store"] == "persistence.roblox.datastore.PlayerInventory_v1"
            and p["relationship"] == "CONFIGURES_PERSISTENCE"
            for p in persistence
        )
        assert any(
            p["store"] == "persistence.roblox.datastore.PlayerInventory_v1"
            and p["relationship"] == "READS_PERSISTENCE"
            for p in persistence
        )
        assert any(
            p["store"] == "persistence.roblox.datastore.PlayerInventory_v1"
            and p["relationship"] == "WRITES_PERSISTENCE"
            for p in persistence
        )
        assert any(
            p["store"] == "persistence.roblox.datastore.PlayerProfiles_v1"
            and p["relationship"] == "READS_PERSISTENCE"
            for p in persistence
        )

        # 15. Flamework @Service / @Controller / Dependency<T>
        assert any(
            s["relationship"] == "PROVIDES_SERVICE"
            and "CombatService" in s["service"]
            for s in services
        )
        assert any(
            s["relationship"] == "GETS_SERVICE"
            and "CombatService" in s["service"]
            for s in services
        )

        # 16. Standard MCP tools work seamlessly on Luau
        callees = get_callees(con, repo, symbol="InventoryService.HandleInventoryRequest")
        assert callees["count"] >= 1
        callers = get_callers(con, repo, symbol="Types.IsValidItem")
        assert callers["count"] >= 1
        refs = get_references(con, repo, symbol="ReplicatedStorage.Remotes.Inventory")
        assert refs["count"] >= 1
        file_view = get_file(con, repo, "src/server/Services/InventoryService.luau", start_line=1, end_line=25)
        assert "InventoryService" in file_view["content"]

        # 17. ACCEPTANCE SCENARIO:
        # ClientController -> CLIENT_DISPATCHES_REMOTE -> ReplicatedStorage.Remotes.Inventory -> SERVER_HANDLES_REMOTE -> InventoryService
        path_res = trace_path(con, repo, "ClientController", "InventoryService")
        assert path_res["status"] == "ok"
        assert path_res["path_length"] >= 2
        rel_types = [step["relationship"] for step in path_res["path"]]
        assert "CLIENT_DISPATCHES_REMOTE" in rel_types
        assert "SERVER_HANDLES_REMOTE" in rel_types
        # Verify never collapsed into generic CALLS
        for step in path_res["path"]:
            if "Remotes.Inventory" in step["source"] or "Remotes.Inventory" in step["target"]:
                assert step["relationship"] in {"CLIENT_DISPATCHES_REMOTE", "SERVER_HANDLES_REMOTE"}
                assert step["evidence_class"] == "ROJO_VERIFIED"

        # Also test trace_call (trace_flow), analyze_impact, and get_context on the acceptance scenario
        flow_res = trace_call(con, "ClientController", callees=True)
        flow_edge_types = {e["relationship"] for e in flow_res}
        assert "CLIENT_DISPATCHES_REMOTE" in flow_edge_types

        impact_res = analyze_impact(con, "InventoryService")
        assert len(impact_res["impact_items"]) >= 1
        assert any(
            item["relationship"] in {"SERVER_HANDLES_REMOTE", "GETS_SERVICE", "REQUIRES_MODULE"}
            for item in impact_res["impact_items"]
        )

        ctx = get_context(
            con,
            repo,
            task="Trace how ClientController dispatches Inventory remote to InventoryService",
            intent="TRACE",
        )
        assert len(ctx.symbols) >= 1

    # Test CLI subcommands (`codegraph roblox remotes`, `codegraph roblox modules`, `codegraph roblox routes`)
    runner = CliRunner()
    res_remotes = runner.invoke(app, ["roblox", "remotes", "--repo", str(repo), "--json"])
    assert res_remotes.exit_code == 0
    parsed_remotes = json.loads(res_remotes.stdout)
    assert any(r["remote"] == "ReplicatedStorage.Remotes.Inventory" for r in parsed_remotes["remotes"])

    res_modules = runner.invoke(app, ["roblox", "modules", "--repo", str(repo), "--json"])
    assert res_modules.exit_code == 0
    parsed_modules = json.loads(res_modules.stdout)
    assert parsed_modules["rojo_configured"] is True

    res_routes = runner.invoke(app, ["roblox", "routes", "--repo", str(repo), "--json"])
    assert res_routes.exit_code == 0
    parsed_routes = json.loads(res_routes.stdout)
    assert len(parsed_routes["routes"]) >= 1


def test_roblox_5_mandatory_negative_cases_and_malformed_rojo(tmp_path: Path) -> None:
    """Verify the 5 mandatory negative tests (zero false edges) and malformed default.project.json."""
    repo = tmp_path.resolve()

    # Malformed default.project.json must not crash indexing
    (repo / "default.project.json").write_text("{ malformed json !!!", encoding="utf-8")

    # 1. Dynamic WaitForChild(variable) -> UNKNOWN, never fake remote edge
    # 2. Dynamic require(variable) -> UNKNOWN, never fake module edge
    # 3. Non-Roblox :Connect(...) -> must not create SERVER_HANDLES_REMOTE
    # 4. Non-Roblox :FireServer(...) -> must not create ROJO_VERIFIED remote edge
    # 5. Plain non-Roblox Lua file with require("x") -> must not fabricate Rojo paths
    (repo / "plain.lua").write_text(
        """local pkgName = getDynamicName()
local dynMod = require(pkgName)
local plainMod = require("socket.http")

local customSignal = createSignal()
customSignal:Connect(function()
    print("custom signal fired")
end)

local fakeSocket = createCustomRpc()
fakeSocket:FireServer("hello")

local ReplicatedStorage = game:GetService("ReplicatedStorage")
local dynRemoteName = getRemoteName()
local dynRemote = ReplicatedStorage:WaitForChild(dynRemoteName)
dynRemote:FireServer("payload")
""",
        encoding="utf-8",
    )

    indexer = Indexer(repository=repo, settings=Settings())
    summary = indexer.index()
    assert summary["indexed"] == 1

    with indexer.session() as con:
        # Verify no SERVER_HANDLES_REMOTE was created for customSignal:Connect
        sh_rows = con.execute(
            "SELECT * FROM graph_edges WHERE relationship = 'SERVER_HANDLES_REMOTE'"
        ).fetchall()
        assert len(sh_rows) == 0

        # Verify no ROJO_VERIFIED remote edge was created
        cd_rows = con.execute(
            "SELECT * FROM graph_edges WHERE relationship = 'CLIENT_DISPATCHES_REMOTE'"
        ).fetchall()
        for row in cd_rows:
            assert row["evidence_class"] == "UNKNOWN"
            assert row["confidence"] == "UNKNOWN"

        # Verify no verified reference in 'references' table for CLIENT_DISPATCHES_REMOTE or REQUIRES_MODULE
        ver_refs = con.execute(
            "SELECT * FROM 'references' WHERE relationship IN ('CLIENT_DISPATCHES_REMOTE', 'SERVER_HANDLES_REMOTE', 'REQUIRES_MODULE')"
        ).fetchall()
        assert len(ver_refs) == 0

        # Verify dynamic require(pkgName) and plain Lua require("socket.http") are UNKNOWN and do not fabricate Rojo paths
        req_rows = con.execute(
            "SELECT * FROM graph_edges WHERE relationship = 'REQUIRES_MODULE'"
        ).fetchall()
        assert len(req_rows) >= 2
        for r in req_rows:
            assert r["evidence_class"] == "UNKNOWN"
            assert not str(r["target"]).startswith("ReplicatedStorage")


def test_luau_indexing_performance_100_and_1000_files(tmp_path: Path) -> None:
    """Benchmark indexing speed on 100 and 1,000 Luau files."""
    repo_100 = (tmp_path / "luau_100").resolve()
    repo_100.mkdir(parents=True, exist_ok=True)
    for i in range(100):
        (repo_100 / f"Module_{i}.luau").write_text(
            f"""--!strict
export type Config_{i} = {{ id: number }}
local Module_{i} = {{}}
function Module_{i}:Run(x: number): number
    return x + {i}
end
return table.freeze(Module_{i})
""",
            encoding="utf-8",
        )

    t0 = time.perf_counter()
    idx_100 = Indexer(repository=repo_100, settings=Settings())
    sum_100 = idx_100.index()
    elapsed_100 = time.perf_counter() - t0
    assert sum_100["indexed"] == 100
    assert elapsed_100 < 15.0

    repo_1000 = (tmp_path / "luau_1000").resolve()
    repo_1000.mkdir(parents=True, exist_ok=True)
    for i in range(1000):
        (repo_1000 / f"Mod_{i}.luau").write_text(
            f"""local Mod_{i} = {{}}
function Mod_{i}.Calc(v: number): number
    return v * 2
end
return Mod_{i}
""",
            encoding="utf-8",
        )

    t1 = time.perf_counter()
    idx_1000 = Indexer(repository=repo_1000, settings=Settings())
    sum_1000 = idx_1000.index()
    elapsed_1000 = time.perf_counter() - t1
    assert sum_1000["indexed"] == 1000
    assert elapsed_1000 < 60.0
