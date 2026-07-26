# Coconut

A desktop project-management application in the spirit of Microsoft Project,
Primavera P6, and ProjectLibre: a WBS/Gantt scheduling tool with critical
path analysis, resource management, and baseline tracking - with file-format
interoperability added once the core engine is solid.

## Scope

**In scope**

- Standalone desktop app (PySide6) for building and managing project
  schedules: WBS (with hierarchy), task dependencies, Gantt visualization,
  CPM scheduling, resource assignment, baselines, and progress tracking.
- Local, single-user project files backed by SQLite.
- Reporting/export (CSV, PDF/image) of schedules and resource data.
- Resource-driven scheduling, per-resource calendars, and fuller leveling
  (see Phase 7/8) as the engine matures beyond the original MVP scope.
- Import/export interoperability with MS Project and Primavera P6 file
  formats, added as a later phase once the core scheduler is stable.

**Out of scope (for now)**

- Multi-user/concurrent editing, server-hosted projects, cloud sync.
- Portfolio-level management across multiple projects.
- Earned value management (EVM), cost/budget tracking beyond basic resource
  cost fields.
- Mobile or web clients.
- Cross-project dependencies.
- Priority-scheme/multi-pass resource leveling - Phase 8 covers wiring up
  the existing single greedy delay-based pass plus incremental
  improvements, not a full leveling engine.
- DI containers, plugin architecture, or a storage abstraction beyond what
  SQLite already gives us. Phase 6 (architecture hardening) tightens
  layering and testability for a solo/small-team desktop app; it
  deliberately stops short of infrastructure that only pays off at
  multi-team scale.

## Scale Target

Designed for projects up to a few thousand tasks. This bounds acceptable
complexity for the scheduler and leveling algorithms (an O(nÃ‚Â²) pass is
fine at this scale), but it does **not** permit unbounded work in Qt paint,
model, or refresh paths. Schedule calculation, variance calculation,
resource allocation checks, file open/save, import/export, and reporting
must be orchestrated by the application layer. Fast calculations may run
synchronously during Phase 6, but the architecture must expose a worker
boundary so expensive recomputation and file IO can move to `QThread` or
`QRunnable` without rewriting UI widgets.

## Objectives

1. Provide a usable single-project scheduling tool: create a WBS, sequence
   tasks with dependencies, and see a correct Gantt chart.
2. Implement a correct CPM engine (forward/backward pass, float, critical
   path highlighting) that matches MS Project/P6 behavior for standard
   dependency types (FS, SS, FF, SF) and lag/lead. **Done (Phase 1).**
3. Support resource assignment with over-allocation detection and usable
   leveling.
4. Support baselines and progress tracking (% complete, variance vs.
   baseline). **Done (Phase 5).**
5. Close remaining gaps vs. full-featured tools like MS Project: WBS
   hierarchy, resource-driven scheduling, per-resource calendars, task
   splitting/recurrence, multiple baselines, and export/reporting.
6. Interoperate with the wider PM ecosystem by reading/writing common file
   formats (MS Project XML/MPP, Primavera XER/XML) so existing project data
   isn't locked out.

## Tech Stack

- **GUI:** PySide6 (Qt for Python)
- **Storage:** SQLite (local `.coco` SQLite files), accessed via the
  stdlib `sqlite3` module - no ORM, versioned migrations in
  `storage/migrations.py`.
- **Scheduling engine:** plain Python, decoupled from the GUI layer so it
  can be unit-tested independently and reused by import/export code.
- **Testing:** `pytest` for the scheduling engine, application workflows,
  storage, and file-format converters. GUI (`ui/`) may still be mostly
  manual QA, but any workflow that can be expressed without Qt must be
  covered through the Qt-free `Application` layer.
- **Static analysis & layering (Phase 6):** `mypy --strict` on `core/`,
  `storage/`, and application orchestration code; `import-linter` (or
  equivalent) enforcing the full dependency rule: `core/` imports no
  `storage/` or `ui/`; `storage/` imports no `ui/`; `ui/` imports no
  repository, scheduler, allocation, variance, leveling, or command modules
  directly. UI may import view models/DTOs and the `Application` facade only.
- **Architecture decisions:** significant, non-obvious design choices
  (the Qt-free core, the calendar seam, the command pattern, the Phase 6
  `Application` split) get a short ADR under `docs/adr/` rather than only
  living in this plan's prose.

## Architecture Sketch

```
main.py                  # entry point: QApplication bootstrap only
docs/
  adr/                    # short architecture decision records
Coconut/
  ui/
    main_window.py       # thin QMainWindow shell: widgets + signal wiring
    gantt_view.py         # Gantt chart widget (custom QGraphicsView)
    wbs_view.py            # task table / outline view (QTableView)
    resource_view.py        # resource sheet
    variance_view.py         # baseline vs. current variance table
    icons.py                  # icon loading/rendering
    theme.py                   # light/dark theme support
    dialogs/                # editors that return DTOs; no Project mutation
  application/            # Qt-free application layer (Phase 6)
    app.py                # Application: owns Project, command history,
                           # file path, dirty flag, cached projections
    view_models.py          # immutable read models consumed by Qt models
                             # (UI-shaped projections, not domain concepts  - 
                             # hence living here rather than in core/)
  core/
    models.py             # Task, Dependency, Resource, Assignment, Baseline
                           # (Money/Duration/Units value types: Phase 7/8)
    scheduler.py            # CPM engine (forward/backward pass, float)
    calendar.py               # working-day/calendar abstraction
    leveling.py                 # resource leveling
    allocation.py                 # over-allocation detection
    variance.py                    # baseline vs. current variance calc
    commands.py                     # undoable Command objects
    project.py                       # Project aggregate, in-memory graph;
                                     # no UI, persistence, or undo stack
    exceptions.py                     # domain exception hierarchy (Phase 6)
  storage/
    migrations.py            # versioned SQLite schema (schema_version table)
    repository.py             # load/save Project <-> SQLite; imports core/
                                # only - no knowledge of Application
  interop/
    msp_xml.py              # MS Project XML import/export (planned)
    mpp_reader.py             # MPP binary reader (planned, later phase)
    p6_xer.py                # Primavera XER import/export (planned)
    p6_xml.py                # Primavera XML import/export (planned)
  tests/
```

Key design principle: **UI emits intent; `Application` executes intent;
domain code mutates the project; read models render state.** The scheduler
operates on plain Python objects (`core/models.py`), not Qt objects or
SQLite rows. The GUI and import/export code translate to and from this
model layer through the application facade, not by reaching into scheduler,
storage, commands, allocation, variance, leveling, or aggregate internals
directly. From Phase 6 onward, `application/app.py`'s `Application` class  - 
not `MainWindow`, table models, QWidget views, or dialogs - owns application
state (current project, file path, command history, dirty flag, cached
schedule/projections) and is the thing GUI actions call into.

`Project` is the domain aggregate. It owns task/resource/dependency state
and enforces invariants, but it must not own application workflow concerns
such as current file path, undo/redo stacks, worker dispatch, dialogs, or
view refresh choreography. Qt models are adapters over immutable read
models; `setData()` may emit an edit intent, but must not apply commands.
Dialogs collect input and return DTOs; they must not mutate `Project`.

The dependency chain is one-directional and package-enforced (see
`tests/test_architecture.py`, which fails the build on a violation):
`core/` (pure domain: no `storage`, no `application`, no `ui`, no Qt, no
sqlite3) is imported by `storage/` (load/save only, still no `application`
or `ui`) and by `application/` (the `Application` facade and its read-model
projections - may import both `core/` and `storage/`, but not Qt or `ui/`),
which is in turn the only layer `ui/` may import from `Coconut.*`
beyond plain read-model DTOs. `Application` living in its own
`Coconut/application/` package, not inside `core/`, is what makes
"`core/` never imports `storage/`" a checkable invariant rather than a
convention: `Application` is the piece that legitimately needs both
`core.project` and `storage.repository` (for save/load), and putting that
need anywhere under `core/` would have forced `core/` to depend on
`storage/`.

## Phased Plan

### Phase 0 - Project setup Ã¢Å“â€¦
venv/PySide6/pytest scaffolding; `.coco` SQLite format decided, with
schema versioned in `storage/migrations.py`.

### Phase 1 - Core data model & CPM engine Ã¢Å“â€¦
`core/models.py` (Task/Dependency/Resource/Assignment/Baseline),
`core/calendar.py`, and `core/scheduler.py`: full CPM (forward/backward
pass, float, cycle detection), all 4 dependency types with lag/lead, all
8 MS Project constraint types including cascading ALAP (3-pass solve).
`core/project.py` aggregate with undoable `Command` objects
(`core/commands.py`).

### Phase 2 - Persistence Ã¢Å“â€¦
`storage/migrations.py` (versioned, append-only schema),
`storage/repository.py` (full-overwrite save/load), round-trip tests.

### Phase 3 - Core GUI (WBS + Gantt) Ã¢Å“â€¦
`ui/main_window.py` shell; `ui/wbs_view.py` flat task table with inline
duration/predecessor editing (`2FS+1, 3SS-2` syntax, entered by row
position not internal id); `ui/gantt_view.py` (critical path, dependency
arrows); GUI edits go through `Command` objects and re-run the scheduler.
Known architectural debt: command application and schedule recomputation
currently happen inside Qt classes. Phase 6 removes that coupling before
hierarchy work begins. Indent/outdent WBS hierarchy was deferred here  - 
see Phase 7.

### Phase 4 - Resources Ã¢Å“â€¦
`ui/resource_view.py` resource sheet (name/rate/max_units, read-only
in-place); `ui/dialogs/assignment_dialog.py` assignment editor;
`core/allocation.py` over-allocation detection with visual highlighting;
`core/leveling.py` greedy delay-based leveling pass (not yet wired to a
GUI action - see Phase 8). Known architectural debt: allocation checks and
assignment mutation currently run from UI classes. Phase 6 moves them behind
`Application` projections and intent methods.

### Phase 5 - Baselines & progress tracking Ã¢Å“â€¦
Baseline snapshot/capture, % complete + actual start/finish on tasks,
`core/variance.py` + `ui/variance_view.py`, tracking Gantt (baseline bars
vs. current). Single active baseline only - see Phase 7 for multiple
baseline slots.

### Phase 6 - Architecture hardening
Done now, before Phase 7 adds hierarchy and Phase 8 adds resource-driven
scheduling. This is not cosmetic cleanup; it is the architectural gate that
prevents Qt widgets from becoming the permanent application layer.
- [x] Extract `application/app.py`: an `Application` class that owns the
      current `Project`, current file path, dirty flag, cached
      schedule/projections, and undo/redo stack, exposing intention-level
      methods (`add_task()`, `edit_task_duration()`,
      `set_predecessors_from_text()`, `capture_baseline()`,
      `save_project()`, `open_project()`, etc.). Qt-free, so it is
      unit-testable without a display. `Project` no longer owns
      undo/redo; it is a domain aggregate, not an application controller.
      `Application` lives in its own `Coconut/application/`
      package rather than under `core/`, since it needs to import
      `storage.repository` for save/load - putting it in `core/` would
      have made "`core/` never imports `storage/`" unenforceable.
      `level_resources()` is not yet exposed here - leveling stays
      unwired to any UI action until Phase 8, per that phase's plan.
- [x] Moved every command application out of `ui/`: `MainWindow`,
      `TaskTableModel`/`WbsView`, `ResourceView`, `AssignmentDialog`,
      `SettingsDialog`, and `TaskConstraintDialog` emit intent or return
      DTOs. `tests/test_architecture.py` fails the build if `ui/` imports
      `core.commands`, `storage.repository`, `core.scheduler`,
      `core.allocation`, `core.variance`, or `core.leveling` directly.
- [x] Shrunk `ui/main_window.py` to a thin shell: builds widgets, owns Qt
      actions/menus/toolbars, asks for user input via dialogs, and wires
      UI intent signals to `Application` methods. It holds no project
      state, file path, save/load logic, command construction, scheduling,
      baseline creation, or undo/redo semantics - those live in
      `application/app.py`.
- [x] Introduced immutable (frozen-dataclass) read models/projections in
      `application/view_models.py`: `TaskRow`, `ResourceRow`,
      `GanttProjection` (bars/dependency arrows/baseline bars),
      `VarianceRow`, `BaselineListItem`, `AssignmentRow`/
      `AssignableResource`. Lives in `application/`, not `core/`, since
      these are UI-shaped projections (row position, pre-resolved names,
      pre-computed Gantt geometry inputs), not domain concepts - `core/`
      itself has no use for them. Qt table models display these;
      `setData()` emits an edit-request signal and does not mutate
      `Project`, apply commands, run scheduling, or rollback.
- [x] Centralized recomputation in `Application.execute()`: every accepted
      command recomputes the full `ProjectionState` (schedule, allocation,
      variance-ready data, Gantt) once, and `MainWindow._refresh_all_views()`
      is the single place that pushes it to every view - no cascading
      `dataChanged` connections or ad hoc per-view `refresh()` calls
      remain. A dedicated Qt/application-state-changed signal was judged
      unnecessary at this scale (`MainWindow` already owns both the
      `Application` instance and every view, so a direct call after each
      intent handler is simpler than a signal only `MainWindow` itself
      listens to); revisit if a second UI surface is ever added.
- [x] `core/exceptions.py`: `CoconutError` base with
      `ValidationError`, `SchedulingError` (parent of the existing
      `CyclicDependencyError`), `NothingToUndoError`, `NothingToRedoError`.
      `Application` raises `ValidationError` for bad predecessor syntax,
      self-referencing predecessors, and cyclic-dependency rollback rather
      than leaking a bare `ValueError`.
- [x] Application-layer tests (`tests/test_app.py`): new project,
      add/edit/remove/reorder task, predecessor edit including invalid
      text and cyclic rollback, add/remove resource, add/remove
      assignment (with over-allocation projection), project settings
      change, capture baseline + baseline selection/variance, undo/redo
      (including empty-stack and redo-cleared-by-new-command cases),
      save/load round trip through `Application`, and projection
      recomputation after each mutation.
- [x] `tests/test_architecture.py` extended beyond the original
      core-vs-Qt/sqlite check into a full four-layer guard: `core/`
      imports none of `storage`/`application`/`ui`/Qt/sqlite3; `storage/`
      may import `core/` but not `application/` or `ui/`; `application/`
      may import `core/` and `storage/` but not Qt or `ui/`; `ui/` may
      import `application/` but not the mutation-surface core modules
      listed above.

Deferred out of this pass (tracked here rather than silently dropped  - 
revisit before or during Phase 7/8, whichever needs them first):
- [ ] Concurrency boundary (worker-safe save/load, scheduling, leveling,
      import/export, report-generation inputs/outputs; queued-signal
      callback contract). Nothing in this pass makes it harder to add
      later - `Application`'s intent methods are already the seam a worker
      would call into - but it is not implemented yet. Needed before any
      of those operations get expensive enough to block the event loop.
- [ ] `Money`/`Duration`/`Units` frozen value types on `core/models.py`
      (replacing bare `float`). Deferred to Phase 7/8 since those are the
      phases that start doing real arithmetic across these fields (cost
      rollup, effort-driven duration); introducing the types now with no
      call sites doing unit-sensitive math would be premature.
- [ ] `mypy --strict` on `core/`/`storage/` and an `import-linter` (or
      equivalent) config enforcing the layering rules as a standalone,
      CI-runnable check. `tests/test_architecture.py` enforces the same
      negative-import rules today via `pytest`, so the rules are tested,
      just not yet via a dedicated static-analysis tool.
- [ ] `docs/adr/` write-ups for the decisions already made (Qt-free core,
      the calendar seam, the command pattern, command-history ownership
      moving to `Application`, read-model projections, the `Application`
      split itself). The decisions are documented in code/module
      docstrings and this plan; formal ADR files are still outstanding.

### Phase 7 - WBS hierarchy & scheduling depth
- [x] WBS hierarchy (summary tasks / nesting): group tasks under a parent
      row, with indent/outdent and multi-level nesting. Implemented as
      `Task.parent_id` (an id reference, keeping task identity independent
      of hierarchy) plus a new Qt-free `core/wbs.py` service that owns
      outline numbering, indent/outdent legality, cycle prevention, depth,
      and summary-rollup computation - not bolted onto `ui/wbs_view.py` or
      `Project`. Sibling/display order reuses the existing flat
      `Project._task_order` (a parent's children are simply the
      subsequence of that order with matching `parent_id`); no second
      order concept was introduced. `Application.indent_task()`/
      `outdent_task()` are the intent methods (via the new `SetTaskParent`
      command); `ui/wbs_view.py` stayed a `QTableView` with an outline-
      number column and indented name column driven by `TaskRow` fields
      (`outline_number`, `depth`, `is_summary`, `can_indent`,
      `can_outdent`) - no `QTreeView` migration this pass.
- [x] Kept scheduling and WBS presentation separate: `Application`
      excludes summary tasks (any task with children) from what it passes
      to `core.scheduler.schedule()`, then calls
      `core.wbs.summary_rollups()` to derive each summary task's
      start/finish/duration/% complete from its leaf descendants
      afterward. `TaskRow.duration_days`/`percent_complete` are the
      rollup values (not the task's own stored fields) whenever
      `is_summary` is true, and `ui/wbs_view.py`'s table model marks
      those columns (plus predecessors) non-editable for summary rows.
- [x] Storage migration (`storage/migrations.py` version 5) adds
      `tasks.parent_id`; older `.coco` files migrate cleanly to a flat
      hierarchy (`parent_id` NULL for every task) with no explicit data
      migration needed. Round-trip tests cover nested hierarchy,
      outline numbering, a pre-migration-5 file loading flat, summary
      rollups, indent/outdent legality/cycle prevention, and undo/redo of
      `SetTaskParent`/reparenting via `RemoveTask`.
      Deferred out of this slice (tracked here, not silently dropped):
      predecessor-reference-after-indent/outdent edge cases beyond what
      the added tests cover, and a `QTreeView`-based WBS pane - both can
      layer on top of `core/wbs.py` without changing its public shape.
- [ ] Task types (Fixed Duration / Fixed Units / Fixed Work) with
      effort-driven duration recalculation when assignments change  - 
      currently durations are fixed inputs regardless of resourcing. This
      must be implemented in the application/domain layer, not dialogs or
      table models, because edits to duration, units, and work affect each
      other and must be validated as one workflow.
- [ ] Task splitting (a task can pause and resume on the Gantt).
- [ ] Recurring tasks (generate a series of linked task instances from a
      recurrence pattern).
- [ ] Multiple baseline slots (MSP-style Baseline1-10) instead of a single
      active baseline; `ui/variance_view.py` gains a baseline selector.

### Phase 8 - Resource management depth
- [ ] Wire `core/leveling.py` through `Application.level_resources()`, not
      directly to a GUI action. The UI may open a preview dialog, but the
      preview data must be an immutable DTO/projection and the final apply
      step must execute a single application-level command or transaction.
- [ ] In-place resource editing: `EditResource` command so name/rate/
      max_units can be edited without remove-and-re-add. Qt models emit an
      edit intent; they do not instantiate or apply the command.
- [ ] Per-resource calendars (working days/hours/vacation per resource,
      layered on the existing global `Calendar`), used by the scheduler
      and over-allocation checks. Calendar changes invalidate schedule and
      allocation projections through `Application`, not per-view refresh
      code.
- [ ] Cost-per-use and overtime rate fields on `Resource`; material/cost
      resource types alongside the existing generic work resource.
- [ ] Resource cost accrual/rollup (assignment cost = rate Ãƒâ€” work, summed
      per task/project) feeding into Phase 9 reporting.

### Phase 9 - Reporting & export
- [ ] CSV export of tasks, resources, and assignments through application
      services using read models/projections, not by scraping Qt widgets.
- [ ] Print/export the Gantt chart to PDF/image. Long exports run through
      the worker boundary defined in Phase 6 and report progress/errors back
      to the UI via queued signals/application callbacks.
- [ ] Basic summary reports (e.g. task list, over-allocated resources,
      variance) exportable alongside the Gantt.

### Phase 10 - Interoperability
- [ ] Before implementation, write a short per-format mapping spec (field
      by field: how MSP/P6 constraints, custom fields, and activity codes
      map onto `core/models.py`) - fidelity round-tripping is a semantic
      reconciliation problem, not just save/load equality.
- [ ] `interop/msp_xml.py`: import/export MS Project XML interchange
      format (well-documented, good first target).
- [ ] `interop/p6_xml.py`: import/export Primavera P6 XML.
- [ ] `interop/p6_xer.py`: import/export Primavera XER (text-based,
      documented format).
- [ ] `interop/mpp_reader.py`: MPP binary format - evaluate existing
      libraries (e.g. Apache POI/MPXJ via a Java bridge, or an existing
      Python MPP reader) before attempting to parse the binary format
      directly; high-effort/high-risk, scope separately once the rest of
      the app is stable.
- [ ] Round-trip fidelity tests against sample files for each format.

### Phase 11 - Polish
- [ ] Gantt bars support drag-to-reschedule (currently view-only; all
      edits go through the WBS table).
- [ ] Keyboard-driven task entry (MS Project-style fast entry).
- [ ] Packaging (PyInstaller) for distribution. Version numbering and
      changelog process are deferred until distribution is imminent.

## Open Questions / Risks

- **MPP binary format** is proprietary and undocumented; likely the
  highest-risk item in the plan. Worth revisiting scope (maybe MPP import
  only, via an existing library, no MPP export) once Phase 10 is reached.
- **WBS hierarchy** (Phase 7, architecture slice done): the structural
  change (hierarchy service, scheduler rollup split, storage schema, read
  models) landed via `core/wbs.py` + `Task.parent_id`, without stuffing
  parent/child rules into `ui/wbs_view.py`. Remaining Phase 7 risk is
  scoped to the not-yet-implemented items in that phase's checklist
  (task types, splitting, recurrence, multiple baselines) plus a
  possible future `QTreeView` migration for the WBS pane.
- **Resource-driven scheduling** (Phase 7/8) means duration is no longer a
  pure input in effort-driven mode; needs a clear rule for how editing
  duration vs. units vs. work interact per task type, matching MSP's model
  closely enough to be intuitive.
- **UI mutation risk** (addressed by Phase 6): the current problem is wider
  than `MainWindow`. Table models, QWidget views, and dialogs currently
  apply commands, run scheduling/allocation/variance calculations, and
  coordinate refreshes. If Phase 6 extracts `Application` but leaves mutation
  in UI classes, the architecture will only look cleaner while remaining
  coupled.
- **Concurrency debt** (addressed by Phase 6/9): SQLite save/load,
  scheduling, leveling, import/export, and PDF/image export can block the
  Qt event loop. Worker boundaries must be designed before these operations
  become expensive enough to force a disruptive rewrite.
- **Interop fidelity** (Phase 10) is a semantic mapping problem (constraint
  vocabularies, custom fields, activity codes), not just round-trip
  equality - each format needs its own short mapping spec before
  implementation.
