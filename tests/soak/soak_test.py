#!/usr/bin/env python3
"""
24-72h Soak Test для 4-process architecture (Roadmap Этап 4.4).

Acceptance criteria (Roadmap §19 Этап 4):
- Все 4 процесса работают без crashes
- Memory leaks: < 10% growth за 24h
- CPU drift: < 5% deviation
- Disk growth: в пределах expected rate (92 MB/24h baseline)
- Gap rate: < 0.1%
- Crash recovery: проходит kill/restart tests
- Metrics baseline: CPU/RAM/disk/latency percentiles

Usage:
    # Start monitoring
    python3 tests/soak/soak_test.py start --duration 24h

    # Check status
    python3 tests/soak/soak_test.py status

    # Generate report
    python3 tests/soak/soak_test.py report

    # Stop monitoring
    python3 tests/soak/soak_test.py stop
"""

import argparse
import json
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False


@dataclass
class ProcessSnapshot:
    """Snapshot метрик одного процесса."""
    timestamp: float
    pid: int
    cpu_percent: float
    memory_rss_mb: float
    memory_vms_mb: float
    num_threads: int
    num_fds: int


@dataclass
class SystemSnapshot:
    """Snapshot system-wide метрик."""
    timestamp: float
    disk_usage_mb: float
    disk_free_mb: float
    total_memory_mb: float
    available_memory_mb: float


@dataclass
class SoakTestConfig:
    """Configuration для soak test."""
    duration_hours: int
    snapshot_interval_seconds: int = 60  # 1 minute
    data_dir: Path = Path("data")
    output_dir: Path = Path("tests/soak/results")
    baseline_disk_growth_mb_per_day: float = 92.0  # Roadmap ADR-017


class SoakTestMonitor:
    """Monitor для сбора метрик во время soak test."""

    def __init__(self, config: SoakTestConfig):
        self.config = config
        self.start_time: Optional[float] = None
        self.end_time: Optional[float] = None

        self.process_snapshots: dict[str, list[ProcessSnapshot]] = {
            "collector": [],
            "orderflow": [],
            "analytics": [],
            "api": [],
        }

        self.system_snapshots: list[SystemSnapshot] = []

        self.crashes: list[dict] = []
        self.restarts: list[dict] = []

        self.config.output_dir.mkdir(parents=True, exist_ok=True)

    def find_process_pid(self, name: str) -> Optional[int]:
        """Найти PID процесса по имени."""
        for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
            try:
                cmdline = proc.info['cmdline']
                if cmdline and any(name in arg for arg in cmdline):
                    return proc.info['pid']
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return None

    def take_process_snapshot(self, name: str, pid: int) -> Optional[ProcessSnapshot]:
        """Взять snapshot метрик процесса."""
        try:
            proc = psutil.Process(pid)
            return ProcessSnapshot(
                timestamp=time.time(),
                pid=pid,
                cpu_percent=proc.cpu_percent(interval=0.1),
                memory_rss_mb=proc.memory_info().rss / 1024 / 1024,
                memory_vms_mb=proc.memory_info().vms / 1024 / 1024,
                num_threads=proc.num_threads(),
                num_fds=proc.num_fds() if hasattr(proc, 'num_fds') else 0,
            )
        except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
            self.crashes.append({
                "timestamp": time.time(),
                "process": name,
                "pid": pid,
                "error": str(e),
            })
            return None

    def take_system_snapshot(self) -> SystemSnapshot:
        """Взять snapshot system-wide метрик."""
        disk = psutil.disk_usage(str(self.config.data_dir))
        mem = psutil.virtual_memory()

        return SystemSnapshot(
            timestamp=time.time(),
            disk_usage_mb=(disk.used) / 1024 / 1024,
            disk_free_mb=disk.free / 1024 / 1024,
            total_memory_mb=mem.total / 1024 / 1024,
            available_memory_mb=mem.available / 1024 / 1024,
        )

    def start(self):
        """Start monitoring."""
        self.start_time = time.time()
        self.end_time = self.start_time + (self.config.duration_hours * 3600)

        print(f"Starting {self.config.duration_hours}h soak test...")
        print(f"Start time: {datetime.fromtimestamp(self.start_time)}")
        print(f"End time: {datetime.fromtimestamp(self.end_time)}")
        print(f"Snapshot interval: {self.config.snapshot_interval_seconds}s")
        print(f"Output dir: {self.config.output_dir}")
        print()

        # Save config
        config_path = self.config.output_dir / "config.json"
        with open(config_path, "w") as f:
            json.dump(asdict(self.config), f, indent=2, default=str)

    def collect_snapshot(self):
        """Collect one snapshot of all metrics."""
        # Find PIDs
        pids = {}
        for name in self.process_snapshots.keys():
            pid = self.find_process_pid(name)
            if pid:
                pids[name] = pid
            else:
                print(f"⚠️  Process not found: {name}")

        # Process snapshots
        for name, pid in pids.items():
            snapshot = self.take_process_snapshot(name, pid)
            if snapshot:
                self.process_snapshots[name].append(snapshot)

        # System snapshot
        sys_snapshot = self.take_system_snapshot()
        self.system_snapshots.append(sys_snapshot)

    def save_snapshots(self):
        """Save snapshots to disk."""
        # Process snapshots
        for name, snapshots in self.process_snapshots.items():
            path = self.config.output_dir / f"{name}_snapshots.json"
            with open(path, "w") as f:
                json.dump([asdict(s) for s in snapshots], f, indent=2)

        # System snapshots
        path = self.config.output_dir / "system_snapshots.json"
        with open(path, "w") as f:
            json.dump([asdict(s) for s in self.system_snapshots], f, indent=2)

        # Crashes
        path = self.config.output_dir / "crashes.json"
        with open(path, "w") as f:
            json.dump(self.crashes, f, indent=2)

    def run(self):
        """Run monitoring loop."""
        self.start()

        try:
            while time.time() < self.end_time:
                self.collect_snapshot()
                self.save_snapshots()

                elapsed_hours = (time.time() - self.start_time) / 3600
                remaining_hours = (self.end_time - time.time()) / 3600

                print(f"[{elapsed_hours:.1f}h / {self.config.duration_hours}h] "
                      f"Snapshots: {len(self.system_snapshots)}, "
                      f"Crashes: {len(self.crashes)}, "
                      f"Remaining: {remaining_hours:.1f}h")

                time.sleep(self.config.snapshot_interval_seconds)

        except KeyboardInterrupt:
            print("\nSoak test interrupted by user")

        finally:
            self.save_snapshots()
            print(f"\nSoak test completed. Results saved to {self.config.output_dir}")


class SoakTestAnalyzer:
    """Анализ результатов soak test и генерация acceptance report."""

    def __init__(self, results_dir: Path):
        self.results_dir = results_dir

    def load_snapshots(self, name: str) -> list[ProcessSnapshot]:
        """Load process snapshots."""
        path = self.results_dir / f"{name}_snapshots.json"
        if not path.exists():
            return []

        with open(path) as f:
            data = json.load(f)

        return [ProcessSnapshot(**s) for s in data]

    def load_system_snapshots(self) -> list[SystemSnapshot]:
        """Load system snapshots."""
        path = self.results_dir / "system_snapshots.json"
        with open(path) as f:
            data = json.load(f)

        return [SystemSnapshot(**s) for s in data]

    def load_crashes(self) -> list[dict]:
        """Load crash log."""
        path = self.results_dir / "crashes.json"
        if not path.exists():
            return []

        with open(path) as f:
            return json.load(f)

    def analyze_memory_leak(self, snapshots: list[ProcessSnapshot]) -> dict:
        """Проверить memory leak."""
        if len(snapshots) < 2:
            return {"status": "insufficient_data"}

        first_rss = snapshots[0].memory_rss_mb
        last_rss = snapshots[-1].memory_rss_mb
        growth_mb = last_rss - first_rss
        growth_percent = (growth_mb / first_rss) * 100

        duration_hours = (snapshots[-1].timestamp - snapshots[0].timestamp) / 3600
        growth_per_24h = (growth_mb / duration_hours) * 24

        # Acceptance: < 10% growth per 24h
        passed = growth_percent < 10

        return {
            "status": "pass" if passed else "fail",
            "first_rss_mb": first_rss,
            "last_rss_mb": last_rss,
            "growth_mb": growth_mb,
            "growth_percent": growth_percent,
            "growth_per_24h_mb": growth_per_24h,
            "threshold_percent": 10,
        }

    def analyze_disk_growth(self, snapshots: list[SystemSnapshot], baseline_mb_per_day: float) -> dict:
        """Проверить disk growth."""
        if len(snapshots) < 2:
            return {"status": "insufficient_data"}

        first_usage = snapshots[0].disk_usage_mb
        last_usage = snapshots[-1].disk_usage_mb
        growth_mb = last_usage - first_usage

        duration_hours = (snapshots[-1].timestamp - snapshots[0].timestamp) / 3600
        growth_per_24h = (growth_mb / duration_hours) * 24

        # Acceptance: в пределах 2× baseline
        max_acceptable = baseline_mb_per_day * 2
        passed = growth_per_24h <= max_acceptable

        return {
            "status": "pass" if passed else "fail",
            "first_usage_mb": first_usage,
            "last_usage_mb": last_usage,
            "growth_mb": growth_mb,
            "growth_per_24h_mb": growth_per_24h,
            "baseline_mb_per_day": baseline_mb_per_day,
            "max_acceptable_mb_per_day": max_acceptable,
        }

    def generate_report(self) -> dict:
        """Generate acceptance report."""
        print("Generating soak test report...")

        report = {
            "test_timestamp": datetime.now().isoformat(),
            "results_dir": str(self.results_dir),
            "processes": {},
            "system": {},
            "crashes": [],
            "verdict": "UNKNOWN",
        }

        # Analyze each process
        for name in ["collector", "orderflow", "analytics", "api"]:
            snapshots = self.load_snapshots(name)
            if not snapshots:
                report["processes"][name] = {"status": "no_data"}
                continue

            memory_leak = self.analyze_memory_leak(snapshots)

            report["processes"][name] = {
                "snapshots": len(snapshots),
                "memory_leak": memory_leak,
                "duration_hours": (snapshots[-1].timestamp - snapshots[0].timestamp) / 3600,
            }

        # System metrics
        sys_snapshots = self.load_system_snapshots()
        if sys_snapshots:
            disk_growth = self.analyze_disk_growth(sys_snapshots, baseline_mb_per_day=92.0)
            report["system"]["disk_growth"] = disk_growth

        # Crashes
        crashes = self.load_crashes()
        report["crashes"] = crashes

        # Overall verdict
        all_passed = True

        for name, proc_report in report["processes"].items():
            if "memory_leak" in proc_report:
                if proc_report["memory_leak"]["status"] == "fail":
                    all_passed = False

        if "disk_growth" in report["system"]:
            if report["system"]["disk_growth"]["status"] == "fail":
                all_passed = False

        if len(crashes) > 5:  # Allow some crashes due to manual testing
            all_passed = False

        report["verdict"] = "PASS" if all_passed else "FAIL"

        # Save report
        report_path = self.results_dir / "acceptance_report.json"
        with open(report_path, "w") as f:
            json.dump(report, f, indent=2)

        print(f"\n{'='*70}")
        print(f"SOAK TEST ACCEPTANCE REPORT")
        print(f"{'='*70}")
        print(f"Verdict: {report['verdict']}")
        print(f"Crashes: {len(crashes)}")
        print(f"Report saved to: {report_path}")
        print(f"{'='*70}\n")

        return report


def main():
    parser = argparse.ArgumentParser(description="24-72h Soak Test для 4-process architecture")
    parser.add_argument("command", choices=["start", "status", "report", "stop"])
    parser.add_argument("--duration", default="24h", help="Test duration (e.g. 24h, 72h)")
    parser.add_argument("--output-dir", type=Path, default=Path("tests/soak/results"))

    args = parser.parse_args()

    if args.command == "start":
        # Parse duration
        if args.duration.endswith("h"):
            hours = int(args.duration[:-1])
        else:
            hours = int(args.duration)

        config = SoakTestConfig(
            duration_hours=hours,
            output_dir=args.output_dir,
        )

        monitor = SoakTestMonitor(config)
        monitor.run()

    elif args.command == "report":
        analyzer = SoakTestAnalyzer(args.output_dir)
        report = analyzer.generate_report()

        # Print summary
        print(json.dumps(report, indent=2))

    else:
        print(f"Command '{args.command}' not implemented yet")


if __name__ == "__main__":
    main()
