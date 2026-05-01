<document>
    <metadata>
        <title>LEDA Turbo Protocol & Dogfooding Calibration Record</title>
        <version>3.4</version>
        <last_updated>2026-05-01</last_updated>
        <purpose>Detailed, AI-readable script of the LEDA algorithm's deep dogfooding process, calibration tuning, and the --auto loop. Serves as immediate context recovery for AI agents.</purpose>
    </metadata>
    
    <section name="Protocol Architecture">
        <description>The LEDA (Logic-Density Evaluation & Drift-Atonement) engine evaluates python code for 'AI Slop' patterns. The Turbo Protocol automates this via `leda_turbo.bat` and `leda_helper.py`.</description>
        <components>
            <component name="leda_turbo.bat">Thin shell wrapper managing the Scan-Fix-Rescan loop across external repositories. Located in `scripts/`.</component>
            <component name="leda_helper.py">Python engine that parses Scan JSONs, ranks files by `fixable_ratio`, and triggers the `--auto` regression-guarded fix loop. Located in `scripts/`.</component>
            <component name="self_calibrator.py">The ML core inside `ai-slop-detector` that tracks `improvement_events` vs `fp_candidates` and calculates `confidence_gap` for DDC and Inflation Weight drift.</component>
        </components>
    </section>

    <section name="Calibration Methodology (Dogfooding)">
        <phase number="1" name="Target Selection">
            Selected structurally diverse repositories: `minGPT`, `unsloth`, `LMCache`, `sloppylint`, `AI-Scientist`, `OpenMythos`.
        </phase>
        <phase number="2" name="Fixable Ratio Selector">
            Initially, the system targeted the highest absolute Deficit Scores, but this caused it to stall on 'Ceiling' files (files with extreme structural debt like `god_function` that cannot be auto-fixed).
            We pivoted to prioritizing by `fixable_ratio = auto-fixable errors / total errors`. This guaranteed high-throughput improvement events.
        </phase>
        <phase number="3" name="The Auto Guard & Regression Check">
            Implemented `--auto` mode. The system automatically applies `bare_except`, `mutable_default_arg`, and `pass_placeholder` fixes.
            Post-fix, a delta check occurs. If `avg_deficit` increases (e.g., the `_auto_install.py` regression in `unsloth`), the protocol automatically performs `git checkout -- <file>` to revert the slop-fix and tags it as a regression.
        </phase>
        <phase number="4" name="Weight Drift Observations">
            Through high-N iterations (N=10 to N=30), we observed LEDA dynamically adjusting weights:
            - **Inflation Weight (Drift +0.10):** Increased when parsing LLM/ML scripts due to frequent empty exceptions (`bare_except`) mapped to low logic density.
            - **DDC Weight (Drift -0.10):** Decreased to normalize the aggressive dependency-check spikes seen in `LMCache` tests.
        </phase>
    </section>

    <section name="Execution Script (For AI Context Recovery)">
        <command_example>
            <code>
            cd D:\Sanctum\ai-slop-detector
            scripts\leda_turbo.bat "D:\Sanctum\Extra Repo\unsloth" 6
            </code>
            <explanation>This triggers the full pipeline: Baseline Scan -> Select Top 6 -> Auto Fix Loop -> Rescan -> Delta Analysis -> Calibration Gate Check.</explanation>
        </command_example>
    </section>
    
    <section name="Target Milestone: The 0.10 Confidence Gap">
        <theory>
            The `confidence_gap` tracks the distance between `improvement_events` density and `fp_candidates`.
            When the gap reaches `0.10`, the system automatically applies the `self_calibrator` weights to the Sentinel V-Engine.
            Current status: Fluctuating due to recent FP noise purge (removing `studio/` ignore rules). Future high-N runs will reliably spike the gap as real fixes accumulate over the purged baseline.
        </theory>
    </section>
</document>
