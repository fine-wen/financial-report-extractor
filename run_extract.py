import os
import subprocess
import sys

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
if not DEEPSEEK_API_KEY:
    DEEPSEEK_API_KEY = input("请输入你的 DeepSeek API Key: ").strip()
os.environ["DEEPSEEK_API_KEY"] = DEEPSEEK_API_KEY
os.environ["MINERU_MODEL_SOURCE"] = "modelscope"

script_dir = os.path.dirname(os.path.abspath(__file__))
batch_py = os.path.join(script_dir, "batch_extract.py")
input_dir = os.path.join(script_dir, "input_pdfs")

if not os.path.exists(input_dir):
    os.makedirs(input_dir)

print("=" * 50)
print("财务报表自动提取工具")

pdfs = [f for f in os.listdir(input_dir) if f.lower().endswith(".pdf")]
if not pdfs:
    print(f"input_pdfs/ 中没有 PDF 文件")
    print(f"请将审计报告 PDF 放入: {input_dir}")
    print("=" * 50)
    input("\n按回车键退出...")
    sys.exit(0)

print(f"发现 {len(pdfs)} 个待处理 PDF")
print("=" * 50)

result = subprocess.run(
    [sys.executable, batch_py, "--run-once"],
    cwd=script_dir,
    env={**os.environ,
         "MINERU_MODEL_SOURCE": "modelscope"},
)

if result.returncode == 0:
    print("\n" + "=" * 50)
    print("全部处理完成！")
else:
    print("\n" + "=" * 50)
    print(f"处理出错，退出码: {result.returncode}")

input("\n按回车键退出...")
