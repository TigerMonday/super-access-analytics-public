"""build_index.py の単体テスト（標準ライブラリのunittestのみ。pytest等の追加インストール不要）。

実行方法:
    python -m unittest discover -s common/report_index/tests
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import build_index as bi  # noqa: E402


def _touch(path: Path, content: str = "# report\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _report_html(*items: tuple[int, str, str]) -> str:
    toc = "".join(
        f'<li class="toc-level-{level}"><a href="#{section}" data-section="{section}">{label}</a></li>'
        for level, section, label in items
    )
    return (
        "<!doctype html><html><head><style>:root{--gray-200:#eee}</style></head><body>"
        '<aside class="report-nav" aria-label="目次"><div class="toc-title">目次</div><ol>'
        f"{toc}</ol><a class=\"back-to-top\" href=\"#report-top\">先頭へ戻る</a></aside>"
        "<main></main></body></html>"
    )


class BuildIndexTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.client_dir = Path(self._tmp.name) / "sample-client"

    # --- 存在しない/空のフォルダで壊れないこと ---------------------------------

    def test_nonexistent_client_dir_does_not_crash(self) -> None:
        html = bi.build_index(self.client_dir, client_id="sample-client")
        self.assertIn("まだ成果物がありません", html)
        self.assertIn("sample-client", html)

    def test_empty_client_dir_does_not_crash(self) -> None:
        self.client_dir.mkdir(parents=True)
        html = bi.build_index(self.client_dir, client_id="sample-client")
        self.assertIn("まだ成果物がありません", html)

    def test_theme_dir_exists_but_empty(self) -> None:
        (self.client_dir / "04_traffic").mkdir(parents=True)
        html = bi.build_index(self.client_dir, client_id="sample-client")
        self.assertIn("基本分析", html)
        self.assertNotIn("04 基本分析", html)
        self.assertIn("まだレポートがありません", html)

    # --- 01: docs/ が一階層深く、check-report以外は出さない -----------------------

    def test_02_measurement_nested_docs_only_check_report(self) -> None:
        base = self.client_dir / "02_measurement"
        _touch(base / "docs" / "check-report.md", "# check report\n")
        _touch(base / "docs" / "check-report-notes.md", "対応メモ\n")
        _touch(base / "docs" / "questions.draft.md", "確認事項\n")
        for i in range(1, 17):
            _touch(base / "docs" / "design-doc" / f"{i:02d}-chapter.md", "章\n")
        _touch(base / "_data" / "phase1.json", "{}")

        sections = bi.build_sections(self.client_dir)
        measurement = next(s for s in sections if s.label == "計測チェック")
        self.assertEqual(len(measurement.reports), 1)
        self.assertEqual(measurement.reports[0].title, "計測チェックレポート")
        self.assertEqual(measurement.reports[0].href, "02_measurement/docs/check-report.md")

    def test_02_measurement_prefers_html_over_md(self) -> None:
        base = self.client_dir / "02_measurement" / "docs"
        _touch(base / "check-report.md")
        _touch(base / "check-report.html", "<html></html>")
        sections = bi.build_sections(self.client_dir)
        measurement = next(s for s in sections if s.label == "計測チェック")
        self.assertEqual(measurement.reports[0].href, "02_measurement/docs/check-report.html")

    def test_html_report_links_same_folder_pdf_as_secondary_action(self) -> None:
        base = self.client_dir / "02_measurement" / "docs"
        _touch(base / "check-report.md")
        _touch(base / "check-report.html", "<html></html>")
        _touch(base / "check-report.pdf", "%PDF")

        sections = bi.build_sections(self.client_dir)
        report = next(s for s in sections if s.label == "計測チェック").reports[0]
        self.assertEqual(report.href, "02_measurement/docs/check-report.html")
        self.assertEqual(report.pdf_href, "02_measurement/docs/check-report.pdf")

        html = bi.build_index(self.client_dir, client_id="sample-client")
        self.assertIn('href="02_measurement/docs/check-report.html">HTMLで見る</a>', html)
        self.assertIn('href="02_measurement/docs/check-report.pdf">PDFを開く</a>', html)

    def test_pdf_action_is_hidden_when_same_folder_pdf_is_missing(self) -> None:
        base = self.client_dir / "04_traffic"
        _touch(base / "basic-analysis-report.html", "<html></html>")
        _touch(self.client_dir / "pdf" / "basic-analysis-report.pdf", "%PDF")

        sections = bi.build_sections(self.client_dir)
        report = next(s for s in sections if s.label == "基本分析").reports[0]
        self.assertIsNone(report.pdf_href)

        html = bi.build_index(self.client_dir, client_id="sample-client")
        self.assertNotIn("PDFを開く", html)

    def test_markdown_primary_can_link_adjacent_pdf(self) -> None:
        base = self.client_dir / "04_traffic"
        _touch(base / "basic-analysis-report.md")
        _touch(base / "basic-analysis-report.pdf", "%PDF")

        html = bi.build_index(self.client_dir, client_id="sample-client")
        self.assertIn('href="04_traffic/basic-analysis-report.md">Markdownで見る</a>', html)
        self.assertIn('href="04_traffic/basic-analysis-report.pdf">PDFを開く</a>', html)

    # --- 03: フラットな構成 -------------------------------------------------------

    def test_04_traffic_basic_report(self) -> None:
        _touch(self.client_dir / "04_traffic" / "basic-analysis-report.md")
        sections = bi.build_sections(self.client_dir)
        traffic = next(s for s in sections if s.label == "基本分析")
        self.assertEqual(len(traffic.reports), 1)
        self.assertEqual(traffic.reports[0].href, "04_traffic/basic-analysis-report.md")

    # --- 02: 日付付きトピックフォルダ ---------------------------------------------

    def test_03_research_topic_subfolders(self) -> None:
        # 複数トピックがあるときは、レジストリの表示名にフォルダ名から推測した
        # 対象名を添えて区別する（表示名だけだと重複してしまうため）。
        base = self.client_dir / "03_research"
        _touch(base / "20260615_competitor" / "00_3c_persona_journey_report.md")
        _touch(base / "20260701_market" / "00_3c_persona_journey_report.md")
        sections = bi.build_sections(self.client_dir)
        research = next(s for s in sections if s.label == "市場顧客分析")
        titles = sorted(r.title for r in research.reports)
        self.assertEqual(
            titles,
            [
                "市場顧客分析（competitor）",
                "市場顧客分析（market）",
            ],
        )

    def test_03_research_single_topic_subfolder_uses_registry_title(self) -> None:
        # トピックが1件だけのときは、フォルダ名を添えずレジストリの表示名だけを出す
        # （他テーマの日本語タイトルの中でフォルダ名だけが浮くのを避ける）。
        base = self.client_dir / "03_research"
        _touch(base / "20260830_サンプル案件_external_research" / "00_3c_persona_journey_report.md")
        sections = bi.build_sections(self.client_dir)
        research = next(s for s in sections if s.label == "市場顧客分析")
        self.assertEqual(len(research.reports), 1)
        self.assertEqual(research.reports[0].title, "市場顧客分析")

    def test_03_research_topic_subfolder_fallback_when_basename_missing(self) -> None:
        base = self.client_dir / "03_research" / "20260615_competitor"
        _touch(base / "summary.md")
        sections = bi.build_sections(self.client_dir)
        research = next(s for s in sections if s.label == "市場顧客分析")
        self.assertEqual(len(research.reports), 1)
        self.assertTrue(research.reports[0].href.endswith("summary.md"))

    # --- 06: 確定版は cvr-improvement-plan 1本だけ。段ごとの個別確定版は探さない ---

    def test_05_cvr_confirmed_shows_only_final_plan(self) -> None:
        base = self.client_dir / "05_cvr"
        _touch(base / "cvr-improvement-plan.md")
        _touch(base / "cvr-improvement-plan.html", "<html></html>")
        past = base / "_past"
        for name in ["01-analysis.md", "02-analysis-review.md", "03-strategy.md", "04-strategy-final.md"]:
            _touch(past / name)
        _touch(past / "2026-08-25_120000_01-analysis.md")

        sections = bi.build_sections(self.client_dir)
        cvr = next(s for s in sections if s.label == "サイト改善")
        self.assertEqual(len(cvr.reports), 1)
        self.assertEqual(cvr.reports[0].title, "サイト改善レポート")
        # htmlがあればhtmlを優先
        self.assertEqual(cvr.reports[0].href, "05_cvr/cvr-improvement-plan.html")
        # ①は確定済み（-final.mdが最新到達点）なので進行中には出ない
        self.assertEqual(cvr.progress, [])

    # --- 06: 3状態（未着手／進行中／確定）の切り分け ------------------------------

    def test_05_cvr_not_started_shows_neither_reports_nor_progress(self) -> None:
        """何も実行していない05_cvrは、確定版も進行中の表示も出ない（「まだレポートがありません」のまま）。"""
        (self.client_dir / "05_cvr").mkdir(parents=True)
        sections = bi.build_sections(self.client_dir)
        cvr = next(s for s in sections if s.label == "サイト改善")
        self.assertEqual(cvr.reports, [])
        self.assertEqual(cvr.progress, [])

        html = bi.build_index(self.client_dir, client_id="sample-client")
        self.assertIn("サイト改善", html)
        self.assertIn("まだレポートがありません", html)
        # 進行中バッジ（実際に表示されるマークアップ）が出ていないことを見る。
        # CSSの説明コメントには「進行中」という語自体が常に含まれるため、単純な文字列一致では見ない。
        self.assertNotIn('<span class="progress-badge">進行中</span>', html)

    def test_05_cvr_in_progress_shows_progress_not_confirmed(self) -> None:
        """01-analysis.mdまで済み、確定版（cvr-improvement-plan.md）はまだ無い状態。"""
        base = self.client_dir / "05_cvr"
        _touch(base / "_past" / "01-analysis.md")
        sections = bi.build_sections(self.client_dir)
        cvr = next(s for s in sections if s.label == "サイト改善")
        self.assertEqual(cvr.reports, [])
        self.assertEqual(len(cvr.progress), 1)
        self.assertEqual(cvr.progress[0].title, "サイト改善レポート（作業中）")
        self.assertEqual(cvr.progress[0].status, "①分析まで完了・検算待ち")
        self.assertEqual(cvr.progress[0].href, "05_cvr/_past/01-analysis.md")

        html = bi.build_index(self.client_dir, client_id="sample-client")
        self.assertIn('<span class="progress-badge">進行中</span>', html)
        self.assertIn("①分析まで完了・検算待ち", html)
        # 確定版のカードは出ない（途中版と確定版が混ざらない）
        self.assertNotIn('<div class="card-title">サイト改善レポート</div>', html)

    def test_05_cvr_analysis_and_review_done_shows_latest_step_only(self) -> None:
        """分析＋検算まで済み、方針作成はまだ（本文シナリオ: ①分析とレビューまで済み、確定版はまだ）。"""
        base = self.client_dir / "05_cvr"
        _touch(base / "_past" / "01-analysis.md")
        _touch(base / "_past" / "02-analysis-review.md")
        sections = bi.build_sections(self.client_dir)
        cvr = next(s for s in sections if s.label == "サイト改善")
        self.assertEqual(cvr.reports, [])
        self.assertEqual(len(cvr.progress), 1)
        self.assertEqual(cvr.progress[0].status, "①分析の検算まで完了・方針作成待ち")
        self.assertEqual(cvr.progress[0].href, "05_cvr/_past/02-analysis-review.md")

    def test_05_cvr_stage1_confirmed_shows_no_progress_entry(self) -> None:
        """①が確定（04-strategy-final.mdが最新到達点）で確定版がある場合は、進行中の表示を出さない。"""
        base = self.client_dir / "05_cvr"
        _touch(base / "cvr-improvement-plan.md")
        for name in ["01-analysis.md", "02-analysis-review.md", "03-strategy.md", "04-strategy-final.md"]:
            _touch(base / "_past" / name)
        sections = bi.build_sections(self.client_dir)
        cvr = next(s for s in sections if s.label == "サイト改善")
        self.assertEqual(len(cvr.reports), 1)
        self.assertEqual(cvr.reports[0].title, "サイト改善レポート")
        self.assertEqual(cvr.progress, [])

    def test_05_cvr_final_marker_without_confirmed_plan_shows_nothing(self) -> None:
        """-final.mdは最新到達点だが確定版がまだ書かれていない（想定外の中断状態）。
        進行中としては出さない（-finalは確定版へ反映済みという前提のため）。"""
        base = self.client_dir / "05_cvr"
        for name in ["01-analysis.md", "02-analysis-review.md", "03-strategy.md", "04-strategy-final.md"]:
            _touch(base / "_past" / name)
        sections = bi.build_sections(self.client_dir)
        cvr = next(s for s in sections if s.label == "サイト改善")
        self.assertEqual(cvr.reports, [])
        self.assertEqual(cvr.progress, [])

    def test_05_cvr_timestamped_past_file_ignored_for_progress(self) -> None:
        """退避済み（時刻プレフィックス付き）のファイルは進行中判定に使わない。"""
        base = self.client_dir / "05_cvr"
        _touch(base / "_past" / "2026-08-25_120000_01-analysis.md")
        sections = bi.build_sections(self.client_dir)
        cvr = next(s for s in sections if s.label == "サイト改善")
        self.assertEqual(cvr.reports, [])
        self.assertEqual(cvr.progress, [])

    def test_05_cvr_empty_past_dir_shows_not_started(self) -> None:
        """_past/ フォルダ自体はあるが空の場合も「未着手」として扱う。"""
        base = self.client_dir / "05_cvr"
        (base / "_past").mkdir(parents=True)
        sections = bi.build_sections(self.client_dir)
        cvr = next(s for s in sections if s.label == "サイト改善")
        self.assertEqual(cvr.reports, [])
        self.assertEqual(cvr.progress, [])

    def test_05_cvr_second_stage_in_progress_after_first_confirmed(self) -> None:
        """①確定（確定版あり）後、②が進行中（page-profile.mdまで）の状態。
        確定版が既にあっても、まだそこに反映されていない②の作業は進行中として出る。"""
        base = self.client_dir / "05_cvr"
        _touch(base / "cvr-improvement-plan.md")
        for name in ["01-analysis.md", "02-analysis-review.md", "03-strategy.md", "04-strategy-final.md"]:
            _touch(base / "_past" / name)
        _touch(base / "_past" / "page-profile.md")
        sections = bi.build_sections(self.client_dir)
        cvr = next(s for s in sections if s.label == "サイト改善")
        self.assertEqual([r.title for r in cvr.reports], ["サイト改善レポート"])
        self.assertEqual(len(cvr.progress), 1)
        self.assertEqual(cvr.progress[0].title, "サイト改善レポート（作業中）")
        self.assertEqual(cvr.progress[0].status, "②ページ分類まで完了・ページ分析待ち")

    def test_05_cvr_second_stage_plan_step_in_progress_after_first_confirmed(self) -> None:
        """①確定（確定版あり）後、②の施策案（07-target-page-plan.md）まで完了・レビュー待ちの状態。

        旧構成では②（対象ページ選定）と③（ABテスト案）が別の段で、この状態は
        07-target-pages.mdまでの進行として表されていたが、1段に統合したことで
        07-target-page-plan.md（選定＋改善案）が最後の「進行中」ステップになる。"""
        base = self.client_dir / "05_cvr"
        _touch(base / "cvr-improvement-plan.md")
        for name in [
            "01-analysis.md",
            "02-analysis-review.md",
            "03-strategy.md",
            "04-strategy-final.md",
            "page-profile.md",
            "05-page-analysis.md",
            "06-page-analysis-review.md",
            "07-target-page-plan.md",
        ]:
            _touch(base / "_past" / name)
        sections = bi.build_sections(self.client_dir)
        cvr = next(s for s in sections if s.label == "サイト改善")
        self.assertEqual([r.title for r in cvr.reports], ["サイト改善レポート"])
        self.assertEqual(len(cvr.progress), 1)
        self.assertEqual(cvr.progress[0].status, "②施策案（対象ページ・改善案）まで完了・レビュー待ち")

    def test_05_cvr_all_stages_confirmed_shows_report_only(self) -> None:
        """①②すべて確定（08-target-page-plan-final.mdが最新到達点）。進行中は出ない。"""
        base = self.client_dir / "05_cvr"
        _touch(base / "cvr-improvement-plan.md")
        for name in [
            "01-analysis.md",
            "02-analysis-review.md",
            "03-strategy.md",
            "04-strategy-final.md",
            "page-profile.md",
            "05-page-analysis.md",
            "06-page-analysis-review.md",
            "07-target-page-plan.md",
            "08-target-page-plan-final.md",
        ]:
            _touch(base / "_past" / name)
        (base / "_past" / "08-target-page-plan-final.md").write_text(
            "- 選定の判定: 妥当\n- 改善案の判定: 妥当\n", encoding="utf-8"
        )
        sections = bi.build_sections(self.client_dir)
        cvr = next(s for s in sections if s.label == "サイト改善")
        self.assertEqual([r.title for r in cvr.reports], ["サイト改善レポート"])
        self.assertEqual(cvr.progress, [])

    def test_05_cvr_rejected_final_stays_in_progress(self) -> None:
        base = self.client_dir / "05_cvr"
        _touch(base / "cvr-improvement-plan.md")
        (base / "_past").mkdir(parents=True, exist_ok=True)
        (base / "_past" / "08-target-page-plan-final.md").write_text(
            "- 選定の判定: 妥当\n- 改善案の判定: 要修正\n", encoding="utf-8"
        )

        sections = bi.build_sections(self.client_dir)
        cvr = next(s for s in sections if s.label == "サイト改善")

        self.assertEqual(len(cvr.progress), 1)
        self.assertEqual(cvr.progress[0].status, "②レビュー差し戻し・対応待ち")

    def test_05_cvr_bold_review_labels_are_recognized_as_confirmed(self) -> None:
        """実際のレビュー出力で使う太字ラベルでも、完了済みと判定する。"""
        base = self.client_dir / "05_cvr"
        _touch(base / "cvr-improvement-plan.md")
        (base / "_past").mkdir(parents=True, exist_ok=True)
        (base / "_past" / "08-target-page-plan-final.md").write_text(
            "- **選定の判定**: 妥当（軽微な指摘つき）\n"
            "- **改善案の判定**: 妥当（軽微な指摘つき）\n",
            encoding="utf-8",
        )

        sections = bi.build_sections(self.client_dir)
        cvr = next(s for s in sections if s.label == "サイト改善")

        self.assertEqual([r.title for r in cvr.reports], ["サイト改善レポート"])
        self.assertEqual(cvr.progress, [])

    # --- 未登録テーマ・想定外ファイルでも壊れない ------------------------------------

    def test_unregistered_theme_folder_uses_fallback(self) -> None:
        _touch(self.client_dir / "07_adhoc" / "adhoc-question.md")
        sections = bi.build_sections(self.client_dir)
        adhoc = next(s for s in sections if s.label == "アドホック分析")
        self.assertEqual(len(adhoc.reports), 1)
        self.assertEqual(adhoc.reports[0].title, "adhoc question")

    def test_unexpected_file_types_are_ignored(self) -> None:
        base = self.client_dir / "04_traffic"
        _touch(base / "basic-analysis-report.md")
        (base / "raw.csv").parent.mkdir(parents=True, exist_ok=True)
        (base / "raw.csv").write_text("a,b\n1,2\n", encoding="utf-8")
        (base / "dump.json").write_text("{}", encoding="utf-8")
        sections = bi.build_sections(self.client_dir)
        traffic = next(s for s in sections if s.label == "基本分析")
        self.assertEqual(len(traffic.reports), 1)

    def test_fallback_excludes_human_authored_looking_files(self) -> None:
        _touch(self.client_dir / "07_adhoc" / "check-report-notes.md")
        _touch(self.client_dir / "07_adhoc" / "questions.draft.md")
        _touch(self.client_dir / "07_adhoc" / "answer.md")
        sections = bi.build_sections(self.client_dir)
        adhoc = next(s for s in sections if s.label == "アドホック分析")
        self.assertEqual([r.title for r in adhoc.reports], ["answer"])

    # --- 利用者向けトップに内部保存先を表示しない ---------------------------------

    def test_index_omits_internal_context_registry_note(self) -> None:
        html = bi.build_index(self.client_dir, client_id="sample-client")
        self.assertNotIn('01_context_management/context/', html)
        self.assertNotIn('登録済みの前提情報', html)
        self.assertNotIn('<div class="callout">', html)

    # --- write_index: 実際にファイルへ書き出す -----------------------------------

    def test_write_index_creates_file(self) -> None:
        _touch(self.client_dir / "04_traffic" / "basic-analysis-report.md")
        out_path = bi.write_index(self.client_dir, client_id="sample-client")
        self.assertTrue(out_path.exists())
        self.assertEqual(out_path.name, "index.html")
        content = out_path.read_text(encoding="utf-8")
        self.assertIn("<!doctype html>", content)
        self.assertIn("sample-client", content)

    def test_write_index_on_nonexistent_dir_creates_it(self) -> None:
        out_path = bi.write_index(self.client_dir, client_id="sample-client")
        self.assertTrue(out_path.exists())
        self.assertTrue(self.client_dir.is_dir())

    def test_write_index_groups_all_report_tocs_as_accordions(self) -> None:
        measurement = self.client_dir / "02_measurement" / "docs" / "check-report.html"
        research = (
            self.client_dir
            / "03_research"
            / "customer_understanding"
            / "00_3c_persona_journey_report.html"
        )
        _touch(measurement, _report_html((2, "summary", "全体サマリー"), (2, "gtm", "GTM設定")))
        _touch(research, _report_html((2, "market", "市場"), (3, "customer", "顧客")))

        bi.write_index(self.client_dir, client_id="sample-client")

        measurement_html = measurement.read_text(encoding="utf-8")
        research_html = research.read_text(encoding="utf-8")
        for html in (measurement_html, research_html):
            self.assertEqual(html.count('<details class="toc-report-group"'), 2)
            self.assertEqual(html.count('name="report-toc"'), 2)
            self.assertEqual(html.count('data-report-current="true" open'), 1)
            self.assertEqual(html.count('id="report-accordion-nav-style"'), 1)
            self.assertIn("計測チェック", html)
            self.assertIn("市場顧客分析", html)

        self.assertIn('href="#summary" data-section="summary"', measurement_html)
        self.assertIn(
            'href="../../03_research/customer_understanding/00_3c_persona_journey_report.html#market"',
            measurement_html,
        )
        self.assertIn('href="#market" data-section="market"', research_html)
        self.assertIn('href="../../02_measurement/docs/check-report.html#summary"', research_html)
        # 別レポートの見出しは現在地判定の対象にしない。
        self.assertEqual(measurement_html.count('data-section="'), 2)
        self.assertEqual(research_html.count('data-section="'), 2)

    def test_write_index_can_rebuild_existing_accordion_without_duplication(self) -> None:
        report = self.client_dir / "04_traffic" / "basic-analysis-report.html"
        _touch(report, _report_html((2, "summary", "分析サマリー")))

        bi.write_index(self.client_dir, client_id="sample-client")
        bi.write_index(self.client_dir, client_id="sample-client")

        html = report.read_text(encoding="utf-8")
        self.assertEqual(html.count('<details class="toc-report-group"'), 1)
        self.assertEqual(html.count('id="report-accordion-nav-style"'), 1)
        self.assertEqual(html.count('data-section="summary"'), 1)


if __name__ == "__main__":
    unittest.main()
