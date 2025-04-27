import gradio as gr
import json
import os
import time
from pathlib import Path
from main import create_sftp_client, upload_file, upload_directory, ensure_remote_dir

def load_config():
    """加载配置文件"""
    try:
        with open('config.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return {
            "host": "",
            "port": 22,
            "username": "",
            "password": ""
        }

def save_config(host, port, username, password):
    """保存配置文件"""
    config = {
        "host": host,
        "port": int(port),
        "username": username,
        "password": password
    }
    with open('config.json', 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=4, ensure_ascii=False)
    return "配置已保存！"

def create_sftp_connection(config, max_retries=3):
    """创建SFTP连接，带重试机制"""
    for attempt in range(max_retries):
        try:
            sftp, transport = create_sftp_client(config)
            return sftp, transport
        except Exception as e:
            if attempt == max_retries - 1:
                raise
            time.sleep(2)  # 等待2秒后重试

def test_connection(host, port, username, password):
    """测试服务器连接"""
    try:
        config = {
            "host": host,
            "port": int(port),
            "username": username,
            "password": password
        }
        sftp, transport = create_sftp_connection(config)
        sftp.close()
        transport.close()
        return "✅ 连接成功！"
    except Exception as e:
        return f"❌ 连接失败：{str(e)}"

def upload_files(files, remote_base_path, progress=gr.Progress()):
    """上传文件到服务器"""
    try:
        config = load_config()
        if not config["host"]:
            return "请先配置服务器信息！"
        
        sftp, transport = create_sftp_connection(config)
        
        try:
            results = []
            for file_obj in progress.tqdm(files, desc="正在上传文件"):
                file_path = file_obj.name
                file_name = os.path.basename(file_path)
                remote_path = os.path.join(remote_base_path, file_name).replace("\\", "/")
                
                try:
                    # 确保远程目录存在
                    remote_dir = os.path.dirname(remote_path)
                    ensure_remote_dir(sftp, remote_dir)
                    
                    # 上传文件
                    for attempt in range(3):  # 最多重试3次
                        try:
                            upload_file(sftp, file_path, remote_path)
                            results.append(f"✅ {file_name} 上传成功")
                            break
                        except Exception as e:
                            if attempt == 2:  # 最后一次尝试失败
                                results.append(f"❌ {file_name} 上传失败：{str(e)}")
                            else:
                                time.sleep(2)  # 等待2秒后重试
                                sftp, transport = create_sftp_connection(config)
                except Exception as e:
                    results.append(f"❌ {file_name} 上传失败：{str(e)}")
            
            return "\n".join(results)
        finally:
            try:
                sftp.close()
                transport.close()
            except:
                pass
    except Exception as e:
        return f"❌ 错误：{str(e)}"

def upload_folder(folder_path, remote_base_path, progress=gr.Progress()):
    """上传文件夹到服务器"""
    try:
        if not folder_path:
            return "请选择要上传的文件夹！"
            
        config = load_config()
        if not config["host"]:
            return "请先配置服务器信息！"
        
        if not os.path.exists(folder_path):
            return f"❌ 错误：文件夹 {folder_path} 不存在"
            
        if not os.path.isdir(folder_path):
            return f"❌ 错误：{folder_path} 不是一个文件夹"
        
        max_retries = 3
        for attempt in range(max_retries):
            try:
                sftp, transport = create_sftp_connection(config)
                try:
                    remote_path = os.path.join(remote_base_path, os.path.basename(folder_path)).replace("\\", "/")
                    upload_directory(sftp, folder_path, remote_path)
                    return f"✅ 文件夹 {os.path.basename(folder_path)} 上传成功！"
                finally:
                    try:
                        sftp.close()
                        transport.close()
                    except:
                        pass
            except Exception as e:
                if attempt == max_retries - 1:  # 最后一次尝试
                    return f"❌ 错误：上传失败 - {str(e)}"
                time.sleep(2)  # 等待2秒后重试
                
    except Exception as e:
        return f"❌ 错误：{str(e)}"

# 加载现有配置
current_config = load_config()

# 创建 Gradio 界面
with gr.Blocks(title="AutoDL 数据传输工具", theme=gr.themes.Soft()) as app:
    gr.Markdown("""
    # 🚀 AutoDL 数据传输工具
    
    这是一个用于将本地数据传输到 AutoDL 服务器的工具。使用 SFTP 协议，支持安全的文件传输。
    """)
    
    with gr.Tab("服务器配置"):
        with gr.Row():
            with gr.Column():
                host = gr.Textbox(label="服务器地址", value=current_config["host"], placeholder="例如：connect.nmb1.seetacloud.com")
                port = gr.Number(label="SSH 端口号", value=current_config["port"])
                username = gr.Textbox(label="用户名", value=current_config["username"], placeholder="例如：root")
                password = gr.Textbox(label="密码", value=current_config["password"], type="password", placeholder="输入你的密码")
                
                with gr.Row():
                    save_btn = gr.Button("💾 保存配置", variant="primary")
                    test_btn = gr.Button("🔍 测试连接")
                
                config_output = gr.Textbox(label="状态信息", interactive=False)
    
    with gr.Tab("文件上传"):
        with gr.Row():
            with gr.Column():
                files = gr.File(label="选择文件", file_count="multiple")
                remote_path_files = gr.Textbox(label="远程目录路径", placeholder="例如：/root/数据", value="/root")
                upload_files_btn = gr.Button("📤 上传文件", variant="primary")
                files_output = gr.Textbox(label="上传状态", interactive=False)
    
    with gr.Tab("文件夹上传"):
        with gr.Row():
            with gr.Column():
                folder = gr.Textbox(label="文件夹路径", placeholder="输入本地文件夹的完整路径")
                remote_path_folder = gr.Textbox(label="远程目录路径", placeholder="例如：/root/数据集", value="/root")
                upload_folder_btn = gr.Button("📁 上传文件夹", variant="primary")
                folder_output = gr.Textbox(label="上传状态", interactive=False)
    
    # 事件处理
    save_btn.click(
        save_config,
        inputs=[host, port, username, password],
        outputs=config_output
    )
    
    test_btn.click(
        test_connection,
        inputs=[host, port, username, password],
        outputs=config_output
    )
    
    upload_files_btn.click(
        upload_files,
        inputs=[files, remote_path_files],
        outputs=files_output
    )
    
    upload_folder_btn.click(
        upload_folder,
        inputs=[folder, remote_path_folder],
        outputs=folder_output
    )

if __name__ == "__main__":
    app.launch(share=False, server_name="127.0.0.1", server_port=7860) 