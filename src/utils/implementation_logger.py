"""実装ログ記録・読み込みユーティリティ"""

import os
import glob
from datetime import datetime
from typing import Dict, List, Optional
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)


@dataclass
class ImplementationLog:
    """実装ログデータクラス"""
    date: str
    feature_name: str
    file_path: str
    summary: str
    implementation_details: List[str]
    technical_specs: List[str]
    test_status: List[str]
    future_tasks: List[str]
    created_at: datetime


class ImplementationLogger:
    """実装ログの記録・読み込みを管理するクラス"""
    
    def __init__(self, docs_dir: str = "_docs"):
        self.docs_dir = docs_dir
        self.ensure_docs_dir()
        
    def ensure_docs_dir(self) -> None:
        """ドキュメントディレクトリを確保"""
        if not os.path.exists(self.docs_dir):
            os.makedirs(self.docs_dir)
            logger.info(f"Created docs directory: {self.docs_dir}")
            
    def log_implementation(self, 
                          feature_name: str,
                          summary: str,
                          implementation_details: List[str],
                          technical_specs: List[str] = None,
                          test_status: List[str] = None,
                          future_tasks: List[str] = None) -> str:
        """実装ログを記録"""
        
        # デフォルト値設定
        technical_specs = technical_specs or []
        test_status = test_status or ["未実装: テストファイル"]
        future_tasks = future_tasks or []
        
        # ファイル名生成
        date_str = datetime.now().strftime("%Y-%m-%d")
        filename = f"{date_str}_{feature_name}.md"
        file_path = os.path.join(self.docs_dir, filename)
        
        # MarkDown形式でログ作成
        content = self._create_log_content(
            feature_name=feature_name,
            summary=summary,
            implementation_details=implementation_details,
            technical_specs=technical_specs,
            test_status=test_status,
            future_tasks=future_tasks
        )
        
        # ファイル書き込み
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
            
        logger.info(f"Implementation log created: {file_path}")
        return file_path
        
    def _create_log_content(self,
                           feature_name: str,
                           summary: str,
                           implementation_details: List[str],
                           technical_specs: List[str],
                           test_status: List[str],
                           future_tasks: List[str]) -> str:
        """ログコンテンツを作成"""
        
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        content = f"""# {feature_name} 実装ログ

## 実装日時
{timestamp}

## 概要
{summary}

## 実装内容
"""
        
        for detail in implementation_details:
            content += f"- {detail}\n"
            
        if technical_specs:
            content += "\n## 技術仕様\n"
            for spec in technical_specs:
                content += f"- {spec}\n"
                
        content += "\n## テスト状況\n"
        for test in test_status:
            if test.startswith("未実装"):
                content += f"- [ ] {test}\n"
            else:
                content += f"- [x] {test}\n"
                
        if future_tasks:
            content += "\n## 今後の課題\n"
            for task in future_tasks:
                content += f"- {task}\n"
                
        return content
        
    def read_all_logs(self) -> List[ImplementationLog]:
        """全ての実装ログを読み込み"""
        logs = []
        pattern = os.path.join(self.docs_dir, "????-??-??_*.md")
        
        for file_path in glob.glob(pattern):
            try:
                log = self._parse_log_file(file_path)
                if log:
                    logs.append(log)
            except Exception as e:
                logger.error(f"Error reading log file {file_path}: {e}")
                
        # 日付順でソート
        logs.sort(key=lambda x: x.created_at, reverse=True)
        return logs
        
    def _parse_log_file(self, file_path: str) -> Optional[ImplementationLog]:
        """ログファイルを解析"""
        filename = os.path.basename(file_path)
        
        # ファイル名から日付と機能名を抽出
        if not filename.startswith(tuple("0123456789")):
            return None
            
        parts = filename.replace(".md", "").split("_", 1)
        if len(parts) != 2:
            return None
            
        date_str, feature_name = parts
        
        try:
            # ファイル内容を読み込み
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
                
            # 基本的な解析（簡易版）
            summary = self._extract_section(content, "概要")
            implementation_details = self._extract_list_items(content, "実装内容")
            technical_specs = self._extract_list_items(content, "技術仕様")
            test_status = self._extract_list_items(content, "テスト状況")
            future_tasks = self._extract_list_items(content, "今後の課題")
            
            # 作成日時を解析
            created_at = datetime.strptime(date_str, "%Y-%m-%d")
            
            return ImplementationLog(
                date=date_str,
                feature_name=feature_name,
                file_path=file_path,
                summary=summary,
                implementation_details=implementation_details,
                technical_specs=technical_specs,
                test_status=test_status,
                future_tasks=future_tasks,
                created_at=created_at
            )
            
        except Exception as e:
            logger.error(f"Error parsing log file {file_path}: {e}")
            return None
            
    def _extract_section(self, content: str, section_name: str) -> str:
        """セクションのテキストを抽出"""
        lines = content.split('\n')
        in_section = False
        section_lines = []
        
        for line in lines:
            if line.startswith(f"## {section_name}"):
                in_section = True
                continue
            elif line.startswith("## ") and in_section:
                break
            elif in_section and line.strip():
                section_lines.append(line.strip())
                
        return '\n'.join(section_lines)
        
    def _extract_list_items(self, content: str, section_name: str) -> List[str]:
        """セクション内のリスト項目を抽出"""
        lines = content.split('\n')
        in_section = False
        items = []
        
        for line in lines:
            if line.startswith(f"## {section_name}"):
                in_section = True
                continue
            elif line.startswith("## ") and in_section:
                break
            elif in_section and line.strip().startswith("- "):
                item = line.strip()[2:].strip()
                # チェックボックス記法を除去
                if item.startswith("[ ] ") or item.startswith("[x] "):
                    item = item[4:]
                items.append(item)
                
        return items
        
    def get_latest_logs(self, limit: int = 10) -> List[ImplementationLog]:
        """最新のログを取得"""
        all_logs = self.read_all_logs()
        return all_logs[:limit]
        
    def get_logs_by_feature(self, feature_name: str) -> List[ImplementationLog]:
        """特定機能のログを取得"""
        all_logs = self.read_all_logs()
        return [log for log in all_logs if feature_name.lower() in log.feature_name.lower()]
        
    def get_implementation_summary(self) -> Dict[str, any]:
        """実装サマリーを取得"""
        logs = self.read_all_logs()
        
        if not logs:
            return {
                "total_implementations": 0,
                "latest_date": None,
                "features": []
            }
            
        features = list(set(log.feature_name for log in logs))
        latest_date = max(log.created_at for log in logs)
        
        return {
            "total_implementations": len(logs),
            "latest_date": latest_date.strftime("%Y-%m-%d"),
            "features": features,
            "recent_implementations": [
                {
                    "feature": log.feature_name,
                    "date": log.date,
                    "summary": log.summary[:100] + "..." if len(log.summary) > 100 else log.summary
                }
                for log in logs[:5]
            ]
        }
        
    def log_startup_reading(self) -> None:
        """起動時のログ読み込み状況を記録"""
        summary = self.get_implementation_summary()
        
        logger.info("=== Implementation Log Summary ===")
        logger.info(f"Total implementations: {summary['total_implementations']}")
        logger.info(f"Latest implementation: {summary['latest_date']}")
        logger.info(f"Features: {', '.join(summary['features'])}")
        
        if summary['recent_implementations']:
            logger.info("Recent implementations:")
            for impl in summary['recent_implementations']:
                logger.info(f"  - {impl['date']}: {impl['feature']}")


# グローバルインスタンス
implementation_logger = ImplementationLogger()


def log_implementation(feature_name: str, 
                      summary: str,
                      implementation_details: List[str],
                      **kwargs) -> str:
    """実装ログを記録（便利関数）"""
    return implementation_logger.log_implementation(
        feature_name=feature_name,
        summary=summary,
        implementation_details=implementation_details,
        **kwargs
    )


def read_implementation_logs() -> List[ImplementationLog]:
    """実装ログを読み込み（便利関数）"""
    return implementation_logger.read_all_logs()


def log_startup_summary() -> None:
    """起動時サマリー表示（便利関数）"""
    implementation_logger.log_startup_reading()