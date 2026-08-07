#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CodeAgent 打包工具
功能：将项目文件打包为 zip 交付包，自动生成 README、依赖清单、使用说明
路径：./scripts/codeagent_packager.py
作者: Evo
日期: 2026-08-07
"""

import os
import sys
import json
import zipfile
import shutil
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List, Optional, Union
from dataclasses import dataclass, asdict, field
import mimetypes

@dataclass
class ProjectFile:
    name: str
    path: str
    content: str
    size: int
    language: str
    description: str = ""


@dataclass
class ProjectInfo:
    name: str
    description: str
    language: str
    dependencies: Dict[str, str] = field(default_factory=dict)
    files: List[ProjectFile] = field(default_factory=list)
    main_file: str = ""
    author: str = "Evo_Gen_3_CodeAgent"
    created_at: str = ""
    install_commands: List[str] = field(default_factory=list)
    usage_commands: List[str] = field(default_factory=list)


class ReadmeGenerator:
    
    @staticmethod
    def generate(project: ProjectInfo) -> str:
        lines = []
        
        # 标题
        lines.append(f"# {project.name}")
        lines.append("")
        
        # 描述
        lines.append(f"## 📖 项目描述")
        lines.append("")
        lines.append(project.description)
        lines.append("")
        
        # 技术栈
        lines.append(f"## 🛠️ 技术栈")
        lines.append("")
        lines.append(f"- **语言**: {project.language}")
        if project.dependencies:
            lines.append("- **依赖**:")
            for dep, version in project.dependencies.items():
                lines.append(f"  - `{dep}=={version}`" if version else f"  - `{dep}`")
        lines.append("")
        
        # 文件结构
        lines.append(f"## 📂 文件结构")
        lines.append("")
        lines.append("```")
        lines.append(project.name + "/")
        for file in project.files:
            prefix = "├── " if file != project.files[-1] else "└── "
            lines.append(f"{prefix}{file.name}  # {file.description}")
        lines.append("```")
        lines.append("")
        
        # 安装
        if project.install_commands:
            lines.append(f"## 📦 安装依赖")
            lines.append("")
            for cmd in project.install_commands:
                lines.append(f"```bash")
                lines.append(cmd)
                lines.append("```")
                lines.append("")
        
        # 使用
        lines.append(f"## 🚀 使用方法")
        lines.append("")
        if project.usage_commands:
            for cmd in project.usage_commands:
                lines.append(f"```bash")
                lines.append(cmd)
                lines.append("```")
                lines.append("")
        else:
            lines.append(f"1. 确保已安装依赖")
            lines.append(f"2. 运行主文件:")
            lines.append(f"```bash")
            lines.append(f"python {project.main_file}" if project.language == 'python' else f"node {project.main_file}")
            lines.append(f"```")
            lines.append("")
        
        # 作者
        lines.append(f"---")
        lines.append("")
        lines.append(f"*由 {project.author} 生成于 {project.created_at}*")
        lines.append("")
        
        return "\n".join(lines)


class DependencyGenerator:   
    @staticmethod
    def generate_requirements(dependencies: Dict[str, str]) -> str:
        lines = []
        for name, version in dependencies.items():
            if version:
                lines.append(f"{name}=={version}")
            else:
                lines.append(name)
        return "\n".join(lines)
    
    @staticmethod
    def generate_package_json(project: ProjectInfo) -> str:
        pkg = {
            "name": project.name.lower().replace(" ", "-"),
            "version": "1.0.0",
            "description": project.description,
            "main": project.main_file,
            "scripts": {
                "start": f"node {project.main_file}"
            },
            "dependencies": {}
        }
        
        for dep, version in project.dependencies.items():
            pkg["dependencies"][dep] = version or "latest"
        
        return json.dumps(pkg, ensure_ascii=False, indent=2)
    
    @staticmethod
    def detect_python_dependencies(code: str) -> Dict[str, str]:
        dependencies = {}
        
        stdlib = {
            'os', 'sys', 're', 'json', 'time', 'datetime', 'math', 'random',
            'collections', 'itertools', 'functools', 'typing', 'argparse',
            'logging', 'subprocess', 'shutil', 'tempfile', 'pathlib',
            'hashlib', 'base64', 'urllib', 'http', 'socket', 'ssl',
            'csv', 'xml', 'html', 'email', 'mimetypes', 'textwrap',
            'threading', 'multiprocessing', 'queue', 'asyncio',
            'unittest', 'doctest', 'pdb', 'traceback', 'inspect'
        }
        
        common_versions = {
            'requests': '2.31.0',
            'flask': '3.0.0',
            'django': '4.2.7',
            'numpy': '1.26.0',
            'pandas': '2.1.0',
            'matplotlib': '3.8.0',
            'scipy': '1.11.0',
            'scikit-learn': '1.3.0',
            'tensorflow': '2.15.0',
            'torch': '2.1.0',
            'transformers': '4.35.0',
            'fastapi': '0.104.0',
            'uvicorn': '0.24.0',
            'pydantic': '2.5.0',
            'sqlalchemy': '2.0.23',
            'pytest': '7.4.0',
            'click': '8.1.0',
            'jinja2': '3.1.0',
            'pillow': '10.1.0',
            'opencv-python': '4.8.1',
            'beautifulsoup4': '4.12.0',
            'selenium': '4.15.0',
            'aiohttp': '3.9.0',
            'httpx': '0.25.0',
            'websockets': '12.0',
            'pyyaml': '6.0',
            'toml': '0.10.2',
            'python-dotenv': '1.0.0',
        }
        
        # 扫描 import 语句
        import re
        import_patterns = [
            r'^import\s+(\w+)',
            r'^from\s+(\w+)\s+import',
            r'^from\s+(\w+)\.\w+\s+import',
        ]
        
        found_imports = set()
        for line in code.split('\n'):
            line = line.strip()
            for pattern in import_patterns:
                match = re.search(pattern, line)
                if match:
                    module = match.group(1)
                    if module not in stdlib and module not in found_imports:
                        found_imports.add(module)
        
        # 映射到依赖
        for module in found_imports:
            if module in common_versions:
                dependencies[module] = common_versions[module]
            else:
                dependencies[module] = ""
        
        return dependencies
    
    @staticmethod
    def detect_node_dependencies(code: str) -> Dict[str, str]:
        dependencies = {}
    
        import re
        patterns = [
            r'(?:require|import)\s*\(\s*[\'"]([^\'"]+)[\'"]\s*\)',
            r'import\s+[\w{}\s*,\n]+\s+from\s+[\'"]([^\'"]+)[\'"]',
            r'import\s+[\'"]([^\'"]+)[\'"]',
            r'export\s+.*\s+from\s+[\'"]([^\'"]+)[\'"]',
            r'import\s*\(\s*[\'"]([^\'"]+)[\'"]\s*\)',
        ]
    
        cleaned = re.sub(r'//.*?$', '', code, flags=re.MULTILINE)
        cleaned = re.sub(r'/\*.*?\*/', '', cleaned, flags=re.DOTALL)
        cleaned = re.sub(r'[\'"].*?[\'"]', '', cleaned)
    
        found = set()
        for pattern in patterns:
            matches = re.findall(pattern, cleaned, re.MULTILINE)
            for m in matches:
                module = m.strip()
                if (module and not module.startswith('.') 
                    and not module.startswith('node:') 
                    and not module.startswith('/')
                    and not module.startswith('@')):
                    # 处理 @scope/package 格式
                    if module.startswith('@') and '/' in module:
                        found.add(module)
                    elif not module.startswith('@'):
                        found.add(module)
    
        for module in found:
            dependencies[module] = ""
    
        return dependencies
        

class ProjectPackager:
    
    def __init__(self, output_dir: str = "./codeagent_workspace/archive"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
    
    def detect_language(self, files: List[ProjectFile]) -> str:
        extensions = {}
        for file in files:
            ext = Path(file.name).suffix.lower()
            if ext:
                extensions[ext] = extensions.get(ext, 0) + 1
        
        if not extensions:
            return 'python'
        
        # 按出现次数排序
        sorted_exts = sorted(extensions.items(), key=lambda x: x[1], reverse=True)
        main_ext = sorted_exts[0][0]
        
        lang_map = {
            '.py': 'python',
            '.js': 'javascript',
            '.ts': 'typescript',
            '.sh': 'shell',
            '.bash': 'shell',
            '.json': 'json',
            '.html': 'html',
            '.css': 'css',
            '.md': 'markdown',
            '.yaml': 'yaml',
            '.yml': 'yaml',
        }
        
        return lang_map.get(main_ext, 'python')
    
    def build_project_info(
        self,
        files: List[ProjectFile],
        name: str,
        description: str,
        main_file: str = None
    ) -> ProjectInfo:
        """构建项目信息"""
        # 检测语言
        language = self.detect_language(files)
        
        # 查找主文件
        if not main_file:
            for file in files:
                if file.name in ['main.py', 'index.js', 'app.py', 'script.sh']:
                    main_file = file.name
                    break
            if not main_file and files:
                main_file = files[0].name
        
        # 检测依赖
        dependencies = {}
        for file in files:
            if file.language == 'python':
                deps = DependencyGenerator.detect_python_dependencies(file.content)
                dependencies.update(deps)
            elif file.language in ['javascript', 'typescript']:
                deps = DependencyGenerator.detect_node_dependencies(file.content)
                dependencies.update(deps)
        
        # 生成安装命令
        install_commands = []
        if dependencies:
            if language == 'python':
                install_commands.append(f"pip install -r requirements.txt")
            elif language in ['javascript', 'typescript']:
                install_commands.append(f"npm install")
        
        # 生成使用命令
        usage_commands = []
        if main_file:
            if language == 'python':
                usage_commands.append(f"python {main_file}")
            elif language in ['javascript', 'typescript']:
                usage_commands.append(f"node {main_file}")
            elif language == 'shell':
                usage_commands.append(f"bash {main_file}")
                usage_commands.append(f"chmod +x {main_file}  # 如果需要执行权限")
        
        return ProjectInfo(
            name=name,
            description=description,
            language=language,
            dependencies=dependencies,
            files=files,
            main_file=main_file or "",
            author="CodeAgent",
            created_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            install_commands=install_commands,
            usage_commands=usage_commands
        )
    
    def pack(
        self,
        files: List[ProjectFile],
        name: str,
        description: str,
        main_file: str = None,
        extra_files: List[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """
        打包项目
        
        Args:
            files: 项目文件列表
            name: 项目名称
            description: 项目描述
            main_file: 主文件名
            extra_files: 额外文件（如 .gitignore 等）
        
        Returns:
            {
                'success': bool,
                'zip_path': str,
                'file_count': int,
                'size': int,
                'error': str
            }
        """
        result = {
            'success': False,
            'zip_path': '',
            'file_count': 0,
            'size': 0,
            'error': None
        }
        
        try:
            # 构建项目信息
            project = self.build_project_info(files, name, description, main_file)
            
            # 创建临时目录
            temp_dir = Path(f"/tmp/codeagent_pack_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
            temp_dir.mkdir(parents=True, exist_ok=True)
            
            try:
                # 创建项目子目录
                project_dir = temp_dir / project.name
                project_dir.mkdir(parents=True, exist_ok=True)
                
                # 写入所有文件
                for file in files:
                    file_path = project_dir / file.name
                    file_path.write_text(file.content, encoding='utf-8')
                
                # 生成 README
                readme_content = ReadmeGenerator.generate(project)
                (project_dir / "README.md").write_text(readme_content, encoding='utf-8')
                
                # 生成依赖文件
                if project.dependencies:
                    if project.language == 'python':
                        req_content = DependencyGenerator.generate_requirements(project.dependencies)
                        (project_dir / "requirements.txt").write_text(req_content, encoding='utf-8')
                    elif project.language in ['javascript', 'typescript']:
                        pkg_content = DependencyGenerator.generate_package_json(project)
                        (project_dir / "package.json").write_text(pkg_content, encoding='utf-8')
                
                # 额外文件
                if extra_files:
                    for extra in extra_files:
                        name = extra.get('name', '')
                        content = extra.get('content', '')
                        if name:
                            (project_dir / name).write_text(content, encoding='utf-8')
                
                # 打包为 zip
                zip_name = f"{project.name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
                zip_path = self.output_dir / zip_name
                
                with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
                    for root, dirs, zip_files in os.walk(project_dir):
                        for file in zip_files:
                            file_path = Path(root) / file
                            arcname = file_path.relative_to(temp_dir)
                            zf.write(file_path, arcname)
                
                # 计算大小
                size = zip_path.stat().st_size
                
                result['success'] = True
                result['zip_path'] = str(zip_path)
                result['file_count'] = len(files) + 2  # + README + requirements/package
                result['size'] = size
                
            finally:
                # 清理临时目录
                shutil.rmtree(temp_dir, ignore_errors=True)
                
        except Exception as e:
            result['error'] = str(e)
        
        return result


# 工具函数

def create_project_file(
    name: str,
    content: str,
    description: str = ""
) -> ProjectFile:
    language = Path(name).suffix.lower().lstrip('.')
    lang_map = {
        'py': 'python',
        'js': 'javascript',
        'ts': 'typescript',
        'sh': 'shell',
        'bash': 'shell',
        'json': 'json',
        'html': 'html',
        'css': 'css',
        'md': 'markdown',
        'yaml': 'yaml',
        'yml': 'yaml',
    }
    
    return ProjectFile(
        name=name,
        path=name,
        content=content,
        size=len(content.encode('utf-8')),
        language=lang_map.get(language, 'text'),
        description=description
    )


# CLI
def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='CodeAgent 打包工具')
    parser.add_argument('--name', type=str, default='my-project', help='项目名称')
    parser.add_argument('--description', type=str, default='', help='项目描述')
    parser.add_argument('--main', type=str, help='主文件名')
    parser.add_argument('--files', type=str, help='文件列表 (JSON 格式)')
    parser.add_argument('--file-dir', type=str, help='文件目录（自动扫描）')
    parser.add_argument('--output', type=str, help='输出路径')
    parser.add_argument('--test', action='store_true', help='运行测试')
    
    args = parser.parse_args()
    
    if args.test:
        print("🧪 运行打包测试...")
        
        # 创建测试文件
        files = [
            create_project_file(
                'main.py',
                '''
import requests
import json

def main():
    print("Hello, World!")
    response = requests.get('https://api.github.com')
    print(f"Status: {response.status_code}")

if __name__ == '__main__':
    main()
''',
                '主程序入口'
            ),
            create_project_file(
                'utils.py',
                '''
def format_json(data):
    import json
    return json.dumps(data, indent=2)

def read_file(path):
    with open(path, 'r') as f:
        return f.read()
''',
                '工具函数'
            ),
        ]
        
        packager = ProjectPackager()
        result = packager.pack(
            files=files,
            name='test-project',
            description='这是一个测试项目'
        )
        
        print(f"成功: {result['success']}")
        print(f"文件: {result['zip_path']}")
        print(f"文件数: {result['file_count']}")
        print(f"大小: {result['size']} bytes")
        
        if result['error']:
            print(f"错误: {result['error']}")
        
        print("✅ 测试完成")
        return
    
    # 读取文件
    files = []
    if args.files:
        data = json.loads(args.files)
        for item in data:
            files.append(create_project_file(
                item.get('name', 'file.txt'),
                item.get('content', ''),
                item.get('description', '')
            ))
    elif args.file_dir:
        dir_path = Path(args.file_dir)
        if dir_path.exists():
            for file_path in dir_path.iterdir():
                if file_path.is_file():
                    content = file_path.read_text(encoding='utf-8')
                    files.append(create_project_file(
                        file_path.name,
                        content,
                        ''
                    ))
    
    if not files:
        print("错误: 请提供 --files 或 --file-dir", file=sys.stderr)
        sys.exit(1)
    
    # 执行打包
    packager = ProjectPackager()
    result = packager.pack(
        files=files,
        name=args.name,
        description=args.description or '由 CodeAgent 生成的项目',
        main_file=args.main
    )
    
    # 输出结果
    if args.output:
        with open(args.output, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2, default=str)
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    
    if result['success']:
        print(f"✅ 打包成功: {result['zip_path']}", file=sys.stderr)
    else:
        print(f"❌ 打包失败: {result['error']}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()