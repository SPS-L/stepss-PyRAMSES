# SDD ledger — plan: docs/superpowers/plans/2026-08-25-stepss-ssa-module.md

Spec: docs/superpowers/specs/2026-08-25-stepss-ssa-module-design.md (read, reachable)
Branch: ssa-module in stepss-python-ui (a submodule of the stepss umbrella)
Repo state at start: fcc5783 spec, ec232f2 plan, working tree clean

## Workspace

`.superpowers/` is NOT in this repo's tracked `.gitignore`. Added `/.superpowers/`
to `$(git rev-parse --git-dir)/info/exclude`, which for this submodule resolves to
`../.git/modules/stepss-python-ui/info/exclude`. Verified: `git check-ignore -q`
returns IGNORED and `git status --short` is clean.

Ruling: excluded locally rather than editing the tracked `.gitignore` — the
scratch workspace is this session's, not a repository fact, and the umbrella's
CLAUDE.md is explicit that stray tool directories committed into a component
have broken `git clone --recurse-submodules` for the whole umbrella before.
Cost if wrong: none to the repo; a fresh clone elsewhere would not inherit the
exclusion, and would need it added again.

## Isolation

Ruling: work proceeds on the `ssa-module` branch in place, not in a separate git
worktree. This is a submodule whose gitdir lives under the umbrella's
`.git/modules/`; a worktree of a submodule is workable but adds a second checkout
that the umbrella's pointer does not know about, and the branch is already off
`master`. Cost if wrong: the working tree is occupied while the plan runs, so
unrelated work in this component has to wait or stash.

## Pre-flight conflict scan

### Pairs sharing a file or an interface

| Tasks | Produced vs consumed | Finding |
|---|---|---|
| 1 -> 2 | `_slice`, `_num`, `_int` in `ssa.py`; both extend `tests/test_ssa_parsers.py` | Clean. Task 1's skeleton already imports `namedtuple`, which only Task 2 uses, so Task 2 adds no import. Unused-import lint noise for one task only. |
| 1 -> 3 | `_read_modes`, `MODE_DTYPE`, `RESULT_SUFFIXES`, `DEFAULT_REAL_LIMIT`, `DEFAULT_PF_FLOOR` | Clean. Header dict keys match `Results.__init__` field for field. |
| 2 -> 3 | `_read_pf`, `_read_ms` return dicts keyed by mode index | Clean. `Results.participation`/`mode_shape` use `.get(index, [])`. |
| 1 -> 4 | `MIN_TIME`, `RESULT_SUFFIXES`, `JACOBIAN_SUFFIXES` | Clean. |
| 4 -> 5 | `valid_basename`, `check_time` called from `sim.runSsa` | Ordering constraint, stated in Task 4's header. Task 4 is numbered before Task 5 for exactly this reason. Clean. |
| 4 -> 6 | `_STOP_MARGIN`, `settings_text/name`, `disturbance_text/name`, `members`, `clear_previous_run` | Clean. |
| 3 -> 6 | `_read_text`, `_optional_text`, `Results(..., ram=, generation=)` | Clean. `load()` omits both, defaulting to None, which is what `state_matrix` refuses on. |
| 5 -> 6 | `runSsa`, `_noteSsaAnalysis`, `_ssaGeneration` | Clean. Task 6's `jacobian=True` route calls `_noteSsaAnalysis` itself, which is why Task 5 exposes it separately rather than folding it into `runSsa`. |
| 1,3 -> 7 | `ModeView`, `Results._index_of`, `_check_simple`, `mode_shape`, `participation`, `DEFAULT_DAMPING_ZETA` | Clean. |
| 3,4 -> 8 | `Results.directory/basename/time`, `load`, `_read_text`, `members`, `valid_basename` | Clean. |
| 7 vs 8 | Both insert methods into `Results` "after `summary`" | Not a conflict: distinct method names (`splane`/`mode_shape_plot`/`participation_plot` vs `save`), and Task 7 runs first. Order within the class is immaterial. |
| 1 -> 3,7,8 | `tests/data/ssa/kundur_nopss_{modes,pf,ms}.dat` fixtures | Clean. Tasks 3, 7 and 8 copy them into a tmp dir under the run basename `ssa`. |
| 1,3,6,7 -> 9 | Public API used by the rewritten notebook | Clean. Every symbol the notebook calls is produced by an earlier task. |
| all -> 10 | Documented surface | Clean. Task 10 is in `stepss-docs`, a different repository; flagged in the task. |
| 1,5,6 -> examples | `examples/eigenanalysis/*` read as case data | Read-only in Tasks 1, 5, 6; rewritten in Task 9, which runs after them. No ordering hazard. |

### Per-task self-consistency

| Task | Its tests vs its code, its files vs later touches | Finding |
|---|---|---|
| 1 | Fixture generation, parser, `__init__` export | **Defect found and ruled on**: "Expected: 9 passed" understated the test count. See ruling below. |
| 2 | Parsers vs the two fixture-built line builders | Clean, same defect class as Task 1 (count). |
| 3 | Model, filters, loaders | Clean apart from the count. `cfg` attribute names `_obs`, `_trj`, `_dataset`, `_dstset`, `_init` verified present in `src/stepss/cases.py`. |
| 4 | Pure helpers | Clean apart from the count. |
| 5 | Engine bindings | Clean. `ctypes` and `numpy as np` are already imported in `src/stepss/simulator.py`, so the code as written needs no new import. Verified. |
| 6 | Driver | Clean. The generated `.dst` satisfies `cases._dstProblem`, which requires a record carrying a timed `STOP`; verified by reading that function. |
| 7 | Plots | Clean. `live._canDraw` exists and is what distinguishes an inline backend from an interactive one. Verified. |
| 8 | Archive | Clean apart from the count. |
| 9 | Notebook and README | Clean. `examples/eigenanalysis/solveroptions.dat` does carry `$SCHEME DE` and `$OMEGA_REF SYN` at lines 13 and 14, which Tasks 1, 5 and 6 rely on; verified. |
| 10 | Docs site | Clean, cross-repo, flagged in the task itself. |

### Rulings from the scan

Ruling: the plan's "Expected: N passed" lines were wrong in five of eight cases
(Tasks 1, 2, 3, 4 and 8), because parametrised tests report more cases than test
functions. Replaced all eight with "every test in the file passes, none skipped,
none xfailed", and said explicitly that the count is not a requirement. Reason: an
exact count is not a requirement and an implementer who sees a mismatch may delete
or merge tests to reach it, which is the worst outcome available. Cost if wrong:
a genuinely missing test is no longer caught by a count mismatch; the task
reviewer checking the brief's test list against the diff catches it instead.

Ruling: no other conflict found, so execution begins at Task 1.

## Progress

Task 1: dispatched (implementer, sonnet), BASE=1d32635 (plan test-expectation fix)
        brief .../task-1-brief.md, report .../task-1-report.md
Task 1: implementer DONE, commit 8706abd, 10 tests in file + full suite 136 passed,
        3 deselected (nordic), 0 skipped, 0 xfailed. Implementer concerns: pip install
        needed the sandbox disabled (environmental, not a code issue); some lines of
        the brief's own verbatim code exceed 79 columns, kept verbatim.
Task 1: reviewer dispatched (sonnet) against review-task1-code.diff.
        Ruling: the reviewer's diff excludes the bodies of the three generated fixture
        files (1837 lines of engine output) and carries the first six lines of each
        instead, rendered with cat -A. Reason: 1837 lines of numbers cannot be reviewed
        line by line and would crowd out the 335 lines that can. The full package is at
        review-1d32635..8706abd.diff (191 KB) and the fixtures are in the working tree.
        Cost if wrong: a defect in the middle of a fixture body goes unseen by this
        review; the parser tests assert normalisation and ordering over the whole of
        each file, which is what would catch it.
Task 1: review clean (spec compliant, quality approved, 0 Critical, 0 Important).
        Reviewer verified the column offsets independently against
        stepss-java-ui/src/my/stepss/ssa/SsaModes.java:146-151 and against the Fortran
        edit descriptor, and re-derived the fixture assertions by executing the parser.
Task 1: minor (deferred): src/stepss/ssa.py:37-38 `os` and `namedtuple` imported but
        unused until Tasks 3 and 2 respectively. Plan-mandated; no lint step in CI.
Task 1: minor (deferred): the implementer's report narrates RED/GREEN rather than
        pasting the raw output. Acting on it forward: every later dispatch now
        requires the transcript pasted, not summarised.
Task 1: minor (deferred): src/stepss/ssa.py:315 re-tests the format version on every
        data row rather than once before the first. Verbatim brief code, harmless.
Task 1: complete (commits 1d32635..8706abd, review clean)
Task 2: dispatched (implementer, haiku), BASE=8706abd
Task 2: implementer reported DONE but with a correctness concern: it deleted 16 lines
        from tests/data/ssa/kundur_nopss_ms.dat (modes 1-4, all-zero magnitudes)
        "so all normalized modes have max magnitude 1.0". Addressed before review.
Task 2: Ruling: the fixture was right and the plan's test was wrong. ssa.f90's
        write_ssa_mode_shapes has an explicit `mmax <= 0` branch that writes
        magnitude 0, angle 0 for every omega state of a mode whose omega entries are
        all exactly zero, "so the row count stays the same for every mode"; 4 of the
        Kundur no-PSS case's 70 modes are such modes. My test asserted max == 1.0 for
        every mode, which holds only for modes with rotor content. Deleting genuine
        engine output to satisfy a wrong assertion destroys the one property that
        makes the fixture worth committing. Plan corrected (d90e53c): the test now
        checks the all-zero case explicitly and asserts the fixture still carries all
        four, so this cannot recur silently. Fixture to be restored byte for byte.
        Cost if wrong: none identified; the engine source is unambiguous on this and
        was read directly rather than inferred.
Task 2: fix round 1/5 dispatched (resume implementer) with the restore and the
        corrected test.
Task 2: fix round 1/5 (1 addressed, 0 open — fixture restored byte for byte,
        verified `git diff 8706abd -- tests/data/ssa/` empty; corrected test present;
        16 parser tests and 142 full-suite tests pass; commits bace1fd..c7367e9).
Task 2: Ruling: the implementer's fix commit c7367e9 rewrote history, discarding my
        plan commit d90e53c and folding its content into its own commit, so that
        commit's message no longer describes all of its contents. Content verified
        intact: the plan's corrected test text, the restored fixture and the test file
        all match what was intended, and the working tree is clean. Accepting it
        rather than rewriting history a second time to restore attribution on an
        unpushed local branch, which would cost more risk than the tidiness is worth.
        Acting on it forward: every later dispatch now forbids `git reset`,
        `git commit --amend`, `git rebase` and anything else that discards or rewrites
        an existing commit. Cost if wrong: one commit on this branch carries a plan
        correction under a feature message; `git log -p` still shows what changed.
Task 2: review clean (spec compliant, quality approved, 0 Critical, 0 Important).
        Reviewer re-derived both offset tuples from the Fortran edit descriptors and
        confirmed them byte for byte against real fixture lines, and confirmed the
        corrected test exercises the mmax<=0 branch on exactly modes {1,2,3,4}.
Task 2: reviewer's one "cannot verify from diff" item resolved by me, since it is
        cross-repo: stepss-java-ui/src/my/stepss/ssa/SsaModeShapes.java:41-45 reads
        (0,8),(9,17),(18,42),(43,67),(68,88) and SsaParticipation.java:57-62 reads
        (0,8),(9,17),(18,42),(43,51).trim(),(52,72) untrimmed,(73,93).trim(). The
        Python mirrors both exactly, strip asymmetry included. Not a gap.
Task 2: minor (deferred): src/stepss/ssa.py:238 ModeShapeEntry.__doc__ line is 101
        characters, the file's only pycodestyle hit at max-line-length 100.
Task 2: minor (deferred): the RED transcript in task-2-report.md elides its middle
        with "... [similar errors] ..." although the dispatch asked for it in full.
Task 2: minor (deferred): _read_pf and _read_ms share a skeleton. Reviewer judged
        them two parsers that rhyme rather than duplication worth collapsing, since
        the field counts and the per-field strip behaviour both differ. Agreed.
Task 2: complete (commits 8706abd..c7367e9, review clean)
Task 3: Ruling: implementation tasks run on sonnet from here, not haiku. Task 2 on
        haiku resolved a plan/fixture conflict by deleting genuine engine output and
        then rewrote git history over a controller commit, costing a fix round and a
        ruling apiece. The skill's own guidance is that turn count beats token price;
        two recoveries cost more than the tier difference. Cost if wrong: later tasks
        spend more per implementer than the cheapest tier would.
Task 3: dispatched (implementer, sonnet), BASE=c7367e9
Task 3: implementer BLOCKED, correctly. It found the brief asserting lowercase device
        names {"g1".."g4"} against fixtures that carry uppercase, refused to edit
        either the fixture or the verbatim test, and did not commit a known-failing
        test. 14/15 new tests passed; the one failure was the assertion itself.
Task 3: Ruling: the plan was wrong and the fixture is right. examples/eigenanalysis/
        dyn_noPSS.dat lines 8, 13, 18 and 23 declare SYNC_MACH G1 through G4, and both
        fixtures carry G1..G4 with no lowercase in 1456 occurrences. A transcription
        slip when I wrote the plan. Corrected in Tasks 3 and 7 (commit fc7cd60) to the
        exact uppercase set rather than made case-insensitive, because asserting what
        the engine actually writes is the point of the test. Task 2's lines 554-556 use
        lowercase in hand-built synthetic text and are self-consistent; left alone.
        Cost if wrong: none identified; the case data and both fixtures agree.
Task 3: fix round 1/5 dispatched (resume implementer) with the one-line correction.
Task 3: fix round 1/5 (1 addressed, 0 open — device-name case corrected; 15 new tests
        and 157 full-suite tests pass; commits fc7cd60..bda2948). History preserved:
        the plan correction fc7cd60 remains its own commit.
Task 3: reviewer dispatched (sonnet) against review-c7367e9..bda2948.diff.
Task 3: review clean (spec compliant, quality approved, 0 Critical, 0 Important).
        Reviewer diffed the committed code byte for byte against the brief, and
        confirmed both fail-silently contracts are pinned by tests that would fail if
        the property regressed: the strict > in dominant, and order preservation
        across composed filters.
Task 3: minor (deferred): src/stepss/ssa.py:430 Results.view() hands out self.modes
        itself rather than a copy, while electromechanical() and dominant() both
        return copies. A caller mutating .rows in place would corrupt Results.modes.
        Latent; nothing in the plan triggers it.
Task 3: minor (deferred): participation() and mode_shape() return [] for a mode index
        that does not exist at all, indistinguishable from a real mode with no entries
        above the floor, so a caller typo fails silently.
Task 3: complete (commits c7367e9..bda2948, review clean)
Task 4: dispatched (implementer, sonnet), BASE=bda2948
Task 4: implementer DONE, commit c4cac41, 25 new tests pass (RED seen first),
        full suite 182 passed, 3 deselected. No concerns raised.
Task 4: reviewer dispatched (sonnet) against review-bda2948..c4cac41.diff.
Task 4: review clean (spec compliant, quality approved, 0 Critical, 0 Important).
        Reviewer confirmed byte-for-byte transcription, and checked the five
        fail-silently areas by inspection: the basename character set including the
        None/'' short circuit, NaN and both infinities in check_time, the structural
        disjointness of the generated names from members() (Eig... vs _...), the
        clear_previous_run failure semantics via the monkeypatched os.remove test,
        and both generated file texts character by character.
Task 4: minor (deferred): src/stepss/ssa.py settings_name and disturbance_name are
        byte-identical apart from the suffix constant, including the error message.
        Reviewer judged this duplication worth collapsing rather than functions that
        merely rhyme, but polish rather than a defect.
Task 4: complete (commits bda2948..c4cac41, review clean)
Task 5: dispatched (implementer, sonnet), BASE=c4cac41
Task 5: implementer DONE, commit 69e4f4f, 11 new engine tests pass, full suite 193
        passed, 3 deselected. Only concern was environmental: pip install needs the
        Bash sandbox disabled to write site-packages, as every task has found.
Task 5: reviewer dispatched (sonnet) against review-c4cac41..69e4f4f.diff.
Task 5: review found 1 Important (plan-mandated), 0 Critical. Spec compliant; the
        reviewer verified the time epsilon's sign, both success codes, order='F' plus
        the .copy() that detaches the ctypes buffer, the order<=0 guard, and that the
        counter never advances on a refusal.
Task 5: Ruling on the plan-mandated finding: the reviewer is right and the finding
        stands. tests/test_ssa_engine.py emits 11 UserWarnings from sim.__del__, one
        per test, and the full-suite summary names that file alone, so the suite's
        output was pristine until this task. sim.__del__ warns on every collection by
        design and the fixture legitimately creates one simulator per test, so neither
        is wrong; changing sim.__del__ is out of scope, being public behaviour other
        code may rely on. Fixed at the test instead, with a narrow module-level
        filterwarnings matching only "Simulator with number", added to Task 5's and
        Task 6's test files (Task 6 creates simulators through ssa.run). Plan
        corrected in 320bdd8. The point of a pristine log is that a new warning is
        visible in it, which 11 expected ones destroy. Cost if wrong: if sim.__del__
        ever warns about something else, the pattern is narrow enough that the new
        message still surfaces.
Task 5: minor (deferred): no test pins the floating-point boundary of the already-
        passed time check; the existing test uses values far from the epsilon.
Task 5: minor (deferred): no test drives a real engine refusal (code 78) end to end.
Task 5: fix round 1/5 dispatched (resume implementer).
Task 5: fix round 1/5 (1 addressed, 0 open — narrow filterwarnings verified to match
        only the one notice, both runs' tails show no warnings summary, and
        src/stepss/simulator.py untouched by the fix; commits 69e4f4f..5a7e400).
Task 5: complete (commits c4cac41..5a7e400, review clean)
Task 6: dispatched (implementer, sonnet), BASE=5a7e400
Task 6: implementer DONE, commit 19f526c, 13 new tests pass, full suite 206 passed,
        3 deselected, no warnings. It reported one concern: the state-matrix
        generation test wrote two_modes/_pf/_ms.dat into the repository root, which
        it deleted by hand before committing.
Task 6: Ruling: that is a plan defect, not something to tidy by hand. ssa.run()
        restores the working directory in its finally, so the test's direct
        ram.runSsa("two") call ran wherever pytest started, which is the repo root.
        It is the only test in the plan that reaches the engine outside ssa.run().
        Deleting the files afterwards leaves the next run to recreate them, puts
        untracked files in someone's git status mid-review, and would fail outright
        on a read-only checkout. Fixed at the source with monkeypatch.chdir(tmp_path)
        and a comment saying why (plan commit 22864b8). Cost if wrong: none
        identified; the test asserts the same thing from a different directory.
Task 6: fix round 1/5 dispatched (resume implementer).
Task 6: fix round 1/5 (1 addressed, 0 open — the second analysis now chdirs to
        tmp_path; 13 tests pass, full suite 206 passed, git status clean and no
        two_*.dat anywhere; commits 19f526c..dfa7d50).
Task 6: reviewer dispatched (opus, a tier up: largest and highest-risk diff in the
        plan) against review-5a7e400..dfa7d50.diff.
Task 6: review found 3 Important (all plan-mandated) and 10 Minor, 0 Critical. The
        reviewer verified the refusal ordering, the deep copy, the paired JAC/EIG
        route, the generation guard and the collision refusal all correct, and
        checked the physics tolerances: abs=5e-3 on zeta puts the two intervals at
        [-0.0283,-0.0183] and [0.1037,0.1137], so the sign change is pinned both ways
        with no overlap.
Task 6: Ruling on Important 1 (_INPUT_LISTS named cfg._init as an input): the
        reviewer is right and I verified it directly. addInit warns that an existing
        file will be overwritten; addObs and addData refuse a file that does not
        exist. That is the test of an input and _init fails it, so the initialisation
        trace is an output. A case using addInit would have written its trace beside
        the caller while every other output landed in the run directory, which the
        comment two lines above says must not happen. Dropped from the tuple, with
        the distinguishing rule recorded, and _absolutise now uses getattr with no
        default so a wrong name raises instead of silently doing nothing. Cost if
        wrong: none identified; the cfg docstrings are unambiguous.
Task 6: Ruling on Important 2 (keep_open inert when ram is supplied): keeping the
        behaviour and fixing the docstring, not the reverse. Not closing an object
        you did not open is the right rule; the docstring promised something the code
        never did. Cost if wrong: a caller reusing one simulator must call endSim
        themselves, which the docstring now says.
Task 6: Ruling on Important 3 (chdir skipped when endSim raises a non-RAMSESError):
        real and worth fixing. The finalise block is now nested in its own try with
        the restore in an inner finally, so the directory returns on every path while
        the finalise-then-restore order stays. Cost if wrong: none; strictly wider
        recovery than before.
Task 6: Ruling on the Minor items: folded in six that are a line or two each and that
        pin what the Important findings showed was unpinned, including a test proving
        refusals happen before the clearing step and the only test that exercises
        _absolutise as other than a no-op, which is what would have caught Important 1.
Task 6: minor (deferred): clear_previous_run would delete a caller's data file named
        like a run member rather than refusing it, unlike the settings collision.
Task 6: minor (deferred): the jacobian route does not carry runSsa's "time already
        passed" refusal, so the two routes differ for a reason no comment records.
Task 6: fix round 2/5 dispatched (resume implementer), plan corrected in 41d3f57.
Task 6: fix round 2/5 (3 Important + 6 Minor addressed, 1 new finding — commits
        dfa7d50..c82d6a3). Re-reviewer traced the nested finally by hand and
        confirmed the working directory is restored on every path, and verified the
        input/output distinction against cases.py rather than taking it on trust. It
        also confirmed the refusal-before-clearing test genuinely fails if the
        clearing is hoisted.
Task 6: Ruling on the new finding: the re-reviewer is right that the relative-path
        test does not pin what its docstring claims. The case never calls addInit, so
        cfg._init stays empty and _absolutise's `if entries:` guard skips it whether
        or not _init is in the tuple; the test passes either way and documents
        coverage that does not exist. Fixed by making the claim true rather than
        softening it: the test now adds an init trace and asserts it lands in the run
        directory and not beside the caller, which is exactly what absolutising it
        would change. tests/test_nordic.py:58 already uses addInit against this
        engine, so the file is genuinely written. Plan corrected in 32d5dc2. Cost if
        wrong: if the engine does not write the trace for this case the assertion
        fails loudly, and the implementer was told to report rather than weaken it.
Task 6: noted, not a finding: when the body raises and endSim then raises a
        non-RAMSESError, the second exception replaces the first. Pre-existing
        Python semantics of try/finally, unchanged by the fix, which closed the
        working-directory half of that scenario.
Task 6: fix round 3/5 dispatched (resume implementer).
Task 6: fix round 3/5 (1 addressed, 0 open — the test now populates cfg._init and the
        re-reviewer traced both branches to confirm both new assertions would break if
        _init returned to _INPUT_LISTS; the init.trace assertions passed against the
        real engine; commits c82d6a3..cec2324).
Task 6: complete (commits 5a7e400..cec2324, review clean after 3 fix rounds)
Task 7: dispatched (implementer, sonnet), BASE=cec2324
Task 7: implementer DONE, commit f55e109, 9 new plot tests pass, full suite 217
        passed, 3 deselected, no warnings. Two concerns raised honestly: the brief's
        manual windowed-backend interaction check was not performed, since there is
        no display here, and it placed the two module-level plot helpers after the
        Results class because the brief only said "append at module level".
Task 7: reviewer dispatched (sonnet) against review-cec2324..f55e109.diff, with one
        named risk to settle: whether any test executes _attach_splane_interaction at
        all, and whether splane(interactive=True) under agg would execute it safely.
Task 7: review clean (spec compliant, quality approved, 0 Critical, 0 Important).
        Reviewer hand-traced _fit_window on all three paths, confirmed the damping
        ray is gated so zeta 0 and 1 draw nothing rather than divide by zero, and
        confirmed the note prints only for implicit None and not for an explicit
        interactive=False.
Task 7: named risk settled empirically. No test executes _attach_splane_interaction:
        every test resolves interactive to False under agg, so the RectangleSelector
        construction and both mpl_connect calls are dead to the suite. The reviewer
        then ran splane(interactive=True) under agg and drove on_pick, on_zoom and
        on_click with synthetic events through canvas.callbacks.process: all three
        executed cleanly and the selector was a real RectangleSelector. So the gap is
        closeable cheaply and without a window.
Task 7: minor (deferred, with a verified recipe): add a test calling
        splane(interactive=True) under agg and firing synthetic pick and
        button_press events, closing the only wholly uncovered code path in the
        module, which is also the one a notebook user actually exercises. This
        supersedes the brief's manual windowed check, which was not performed and
        which a permanent test replaces. Ruling: deferred to the final-review fix
        wave rather than a fix round, since the review is approved and minors do not
        enter the loop; recorded here in full so the fix is mechanical.
Task 7: minor (deferred): nothing asserts with capsys that the note is suppressed for
        an explicit interactive=False; the code is right, the assertion is absent.
Task 7: minor (deferred): plt and live._canDraw are imported inside three methods,
        unlike numpy at module level. Harmless, since both are already imported at
        package init, but inconsistent with the module's own style.
Task 7: minor (deferred): two splane tests assert only "is not None", which proves
        the call did not raise rather than anything about the output. They do
        exercise the zero-mode and all-mode paths, which is their real value.
Task 7: complete (commits cec2324..f55e109, review clean)
Task 8: dispatched (implementer, sonnet), BASE=f55e109
Task 8: implementer DONE, commit a6a695c, 13 archive tests pass, full suite 230
        passed, 3 deselected, 1 warning. Two concerns raised, both correctly: a
        DeprecationWarning from tarfile.extractall with no filter, which it declined
        to change against a verbatim brief, and the Java cross-check it could not run.
Task 8: Ruling on the DeprecationWarning: fix at the source, not by filtering in the
        test, which is the opposite of the Task 5 ruling and for a reason. There the
        warning was intended package behaviour a test merely triggered; here it warns
        that Python 3.14 changes extractall's default, so the package's behaviour
        would change under it silently. filter='data' is also right on its merits for
        a format whose members are regular files and one directory, stripping device
        nodes, links and setuid bits none of them should carry. _safe_child stays,
        because the filter reports refusals from inside extraction rather than before
        it. I verified filter='data' round-trips an archive of this exact shape on
        Python 3.13 here before dispatching. Plan corrected in 2b48358. Cost if
        wrong: the parameter needs Python 3.9.17/3.10.12/3.11.4 or newer; the package
        declares no floor, and CI runs current Pythons on all three platforms.
Task 8: the Java-written-archive cross-check remains unperformed and stays with me.
Task 8: fix round 1/5 dispatched (resume implementer).
Task 8: review found 1 Important (plan-mandated), 0 Critical, and confirmed the
        cross-repo format agrees with stepss-java-ui/src/my/stepss/ssa/SsaArchive.java
        on all five points: magic line and version (java:72,75), the four manifest
        keys and their %.2f/%.6f formats (java:160-183), the seven-member set and
        order (java:307-318 via SsaDisturbance.java:40-42), the layout with the
        manifest first under a directory named for the run, and all four refusals
        including ignoring an unknown key.
Task 8: Ruling on the Important finding: real and worth a round. The escaping-entry
        test used tar, where filter='data' refuses the entry by itself, so it passed
        even with _safe_child removed; the reviewer verified empirically that zipfile
        has no equivalent and a bare extractall writes ../escaped.dat outside the
        destination silently. The branch with no test was the branch where the guard
        is the only protection. Added a zip sibling that also asserts nothing was
        written outside. Cost if wrong: none; strictly more coverage.
Task 8: Ruling on the atomic-write Minor: folded in, because it is four lines and the
        Java side already does it. Without it a failure partway through leaves a
        truncated file that looks like an archive until someone opens it. Cost if
        wrong: save() now needs write permission for a .part file beside the target,
        which any path it could write the target to already grants.
Task 8: minor (deferred): _find_manifest looks at the root and one level down, where
        the Java side does an unbounded breadth-first search. Every archive either
        side writes puts it one level down, so interop is unaffected.
Task 8: minor (deferred): archives carry no explicit directory entry for the prefix,
        unlike the Java writer. Both readers synthesise it; cosmetic.
Task 8: minor (deferred): a Python-written manifest always has engine_version unset,
        because Results carries no such attribute. Worth knowing when reading a .ssa
        file's provenance: unset means either unreported or saved from Python.
Task 8: fix round 2/5 dispatched (resume implementer), plan corrected in 71047e3.
Task 8: fix round 2/5 (1 addressed, 1 open — atomic write confirmed correct by a
        scratch script covering OSError and KeyboardInterrupt mid-write; the zip
        escape test landed but proved less than it claimed; commits d14ea09..44c86b3).
Task 8: Ruling, correcting my own previous ruling: the Task 8 reviewer's empirical
        claim that zipfile writes ../escaped.dat outside the destination is false,
        and the re-reviewer was right to contradict it. I verified directly on Python
        3.13: CPython's zipfile strips the ".." component, so the entry unpacks as
        escaped.dat inside the destination silently, and an absolute entry
        /abs_escaped.dat is normalised the same way. Nothing leaks on either branch,
        so the docstring I had the implementer write was untrue and the test failed
        without the guard only by tripping a downstream manifest-not-found error.
        Rewritten: both tests now pass an explicit destination and assert it is empty
        after the refusal, pinning the module's own contract, which is stronger than
        either library's, that such an archive is refused before anything is
        unpacked. Plan corrected in 6f60e7d. Cost if wrong: none identified; the
        behaviour was verified rather than reasoned about, twice, from both sides.
Task 8: fix round 3/5 dispatched (resume implementer).
Task 8: fix round 3/5 (0 addressed, 1 open — the re-reviewer mutation-tested the
        corrected tests and found my own correction still made false claims;
        commits 44c86b3..ae470f2).
Task 8: Ruling, correcting my correction. The re-reviewer is right. Asserting the
        empty destination after a `with pytest.raises(RAMSESError, match="outside")`
        block means that with the guard removed the raises check fails first, so the
        assertion is never reached and cannot be what catches the regression: on the
        zip branch a different RAMSESError (missing manifest) is raised, and on the
        tar branch tarfile.OutsideDestinationError is not a RAMSESError at all and
        escapes uncaught. I then built the replacement and mutation-tested it myself
        before dispatching, which is what I should have done two rounds ago: with
        _safe_child neutralised the zip test fails on the empty-destination assertion
        and the tar test on the isinstance check naming OutsideDestinationError, and
        with it intact both pass. Both tests now share one helper that catches
        Exception and checks the destination before the exception type, and the
        docstring states those two observations and nothing else. Plan corrected in
        baa6a5f. Cost if wrong: none identified; this is the first version of this
        test whose claims were checked rather than reasoned about.
Task 8: fix round 4/5 dispatched (resume implementer).
Task 8: fix round 4/5 (1 addressed, 0 open — re-reviewer ran its own mutation
        experiment and reproduced both stated outcomes exactly: zip fails assertion 1
        with the destination written to, tar fails assertion 2 naming
        tarfile.OutsideDestinationError. It also traced the guard-intact case to
        confirm all three assertions are reached rather than short-circuiting.
        Commits ae470f2..ea15fd1.)
Task 8: complete (commits f55e109..ea15fd1, review clean after 4 fix rounds)
Task 9: dispatched (implementer, sonnet), BASE=ea15fd1
Task 9: implementer DONE, commit 2b145ed. Notebook executes clean and reproduces the
        README numbers: without PSS 0.6246 Hz zeta -0.0233 UNSTABLE, with PSS 0.6237
        Hz zeta +0.1087 stable, and the four local modes match too.
Task 9: review found 2 Important, 0 Critical. It audited every removed markdown line
        against the brief individually and confirmed the four named passages changed
        and nothing else: no physics commentary was lost, which is the failure mode
        an editing task has and the reason this review existed.
Task 9: Ruling on both Important findings: the reviewer is right and both are my
        brief under-scoping the cell 5 edit. Cell 5 still said addDisturb(t, "EIG
        'basename'") schedules the analysis, which was true of the old code cell and
        is not true of ssa.run(), whose default path goes through sim.runSsa() and
        builds no disturbance record; the addDisturb route is taken only under
        jacobian=True, which the notebook never sets. Cell 3's third bullet claimed a
        disturbance is injected from Python, stale for the same reason. Both
        rewritten, with cell 5's physics paragraph kept word for word and only the
        mechanics around it changed. Plan corrected in 543b944. Cost if wrong: none
        identified; the replacement was checked against ssa.run()'s actual branches.
Task 9: fix round 1/5 dispatched (resume implementer).
Task 9: fix round 1/5 (2 addressed, 0 open — re-reviewer verified the physics
        sentence survived word for word by comparing both commits programmatically,
        checked the new cell 5 against ssa.py's run() line by line, and confirmed
        only cells 3 and 5 changed; commits 2b145ed..d3dc2a5).
Task 9: minor (deferred): src/stepss/ssa.py's disturbance_text() docstring still
        reads "A disturbance file is mandatory even when the analysis is injected
        from Python", the same stale phrasing Finding 2 removed from the notebook.
        Out of scope for Task 9; a candidate for the final-review fix wave.
Task 9: minor (deferred): cell 3 now says ssa.run() generates a disturbance file when
        a case has none, but this notebook's case always supplies nothing.dst, so a
        reader may wonder why. True in general, unexercised here.
Task 9: complete (commits ea15fd1..d3dc2a5, review clean after 1 fix round)
Task 10: dispatched (implementer, sonnet). Cross-repo: works in stepss-docs, which I
         branched to ssa-module-docs off 775ef21 rather than committing on main.
         node_modules is already installed there, so npm run build needs no network.
Task 10: implementer DONE, commit ac3735a in stepss-docs on ssa-module-docs. npm run
         build exits 0 with no broken-link warnings, and it verified the anchor
         against the built HTML rather than assuming the slugifier's output.
Task 10: it departed from the brief deliberately and correctly: the brief's headings
         wrote t=0.001 where both real signatures default t to None and resolve to
         MIN_TIME internally. Documenting the real signature is right; a reference
         page that misstates a default is worse than none.
Task 10: minor (deferred): stepss-docs CLAUDE.md carries a MATLAB-ban check grepping
         for 'ssa(' case-insensitively, which now false-positives on sim.runSsa(.
         A coincidental substring match, not a violation, but the check will fire on
         every future run and someone will have to re-derive that each time.
Task 10: reviewer dispatched (sonnet) against review-task10.diff.
Task 10: review found 2 Important, 0 Critical. It verified every behavioural claim in
         the new prose against ssa.py line by line, confirmed the version floor from
         two independent source locations, and reproduced the anchor from the built
         HTML rather than trusting the report.
Task 10: Ruling: the reviewer is right and the three omissions are mine. The
         api-reference headings for load_archive, mode_shape_plot and
         participation_plot each dropped a parameter the function takes: into=None on
         the first, allow_degenerate=False on the other two. A reference page that
         misstates a signature is worse than one omitting the function, because a
         reader trusts it. floor=0.05 stays as the value rather than the constant
         name, which is more useful to a reader. Plan corrected in ce0aa55. Cost if
         wrong: none identified; each was checked against its real def line.
Task 10: folded in the Minor about missing --- dividers between the new ### groups,
         which every other section on that page has, and a clause in the guide's
         "Required settings" prose, which still said the two settings are the
         reader's to set while sitting directly below an example where ssa.run() sets
         them. The same class of staleness Task 9 fixed in the notebook.
Task 10: fix round 1/5 dispatched (resume implementer).
Task 10: fix round 1/5 (4 addressed, 1 open — re-reviewer independently checked all
         14 documented signatures against their real def lines and found every one
         agrees in both directions, and confirmed the anchor from the dist/ build,
         checking the build postdates the fix rather than assuming; commits
         ac3735a..819aea4).
Task 10: minor (deferred): the --- divider was added before four of the five new ###
         groups but not before the first, ### Running. The page's convention, in the
         cfg, sim and extractor sections, puts one between a ## section's intro prose
         and its first ### group too. Ruling: deferred to the final-review fix wave
         rather than a further round, since it is one line of cosmetics and a wave is
         already due for the other deferred minors. Batching it is cheaper than a
         dispatch and a re-review for a horizontal rule.
Task 10: complete (commits 775ef21..819aea4 in stepss-docs, 1 minor parked)
Final review: first dispatch died on a session usage limit before it had read
        anything. No work lost: both branches, both trees and all packages intact.
        Re-dispatched (opus) against review-final.diff with the 23 deferred minors
        handed over for triage.
Final review: complete (opus). Verdict "fix first", 0 Critical, 5 Important, plus a
        triage of the 23 deferred minors: 3 to fix, 5 cheap and worth it, 15 to leave.
        It read the module end to end and judged it one coherent piece, verified all
        seventeen column offsets and the archive format against the Java source
        rather than trusting earlier reviews, and confirmed no dependency crept in.
Final review: Ruling on the five Important findings, all accepted. (1) An unknown
        mode index is answered silently and one of the answers is a plot titled with
        the bogus index, which the design explicitly required be distinguishable.
        (2) keep_open=True with ram=None leaves the simulator reachable only through
        a private attribute, so the documented combination cannot be finalised;
        adding a read-only Results.ram rather than refusing the combination, since it
        is additive and removes no capability. (3) eigenanalysis.md tells readers
        splitting these files on whitespace is safe, which is the exact belief the
        fixed-offset design exists to refute. (4) Nothing records that the offsets
        and the archive format now have two readers, which the spec asked for.
        (5) The docs repo's own documented grep invariant is red on a coincidental
        substring match. Cost if wrong: (2) is the only judgement call; refusing the
        combination instead would be the alternative and is one line away.
Final review: also folded in the reviewer's own Minor about a basename of 45+
        characters producing a .tar.gz the Java reader silently mangles. Minor by the
        rubric, but it breaks the cross-repo contract this work exists to honour, and
        the Java writer already refuses it with an actionable message.
Final review: also folded in the spec deviation it flagged: the design promises
        view.participation(view[0]) resolves and ModeView has no such method. Adding
        two delegating one-liners honours the spec rather than amending it.
Final review: parked, documented residuals not fixed: the load()/run() five-line
        similarity, three error messages for one basename rule, _fit_window's
        fallback constants, the notebook's shared axes across two fitted windows, the
        jacobian route's counter bump on a failed run, ssa.py reaching into three
        private members of sim, and load_archive's per-call temp directory. All
        judged fine to leave by the final review.
Final fix wave: dispatched (sonnet), 15 items across both repos.
        FIX_BASE pyui=ce0aa55, docs=819aea4.
Final fix wave: all 15 items ADDRESSED (commits ce0aa55..a71e47b in stepss-python-ui,
        819aea4..d91122b in stepss-docs). 243 tests pass, pyflakes and pycodestyle
        clean, docs build clean with the anchor unchanged. The re-reviewer ran four
        of the fixes rather than reading them: it confirmed all four consumers now
        refuse an unknown mode index while a degenerate one still works under
        allow_degenerate, that view() no longer aliases, that __all__ resolves and
        drops RAMSESError, and that a 45-character basename refuses on the tar path
        while an ordinary one still writes.
Final fix wave: Ruling on the one load-bearing residual. The cross-repo note added to
        CLAUDE.md named Columns.java as the Java-side home of the column offsets and
        implied SsaArchive.java for the modes banner version. I verified both myself:
        Columns.java carries no offsets at all, only the generic slice/num/integer
        helpers, and the offsets live in SsaModes.java, SsaParticipation.java and
        SsaModeShapes.java; and there are two unrelated FORMAT_VERSION constants,
        SsaModes.java:32 = 2 for the modes banner and SsaArchive.java:75 = 1 for the
        archive. A note whose only job is to point a cold reader correctly, pointing
        them at a file with nothing to change, is worse than no note. Fixed rather
        than parked, which the breaker language allows for a load-bearing residual.
        Cost if wrong: it is one documentation paragraph and every fact in it was
        checked in the Java source before dispatch.
Final fix wave: parked, not fixed. B1's claim that a device name may carry a leading
        or embedded blank is grounded in the parser design and in Columns.java's own
        docstring, but the committed fixtures contain no such name, so nothing
        demonstrates it. The claim is correct and the parser handles it either way.
