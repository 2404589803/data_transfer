import gradio as gr
import json
import os
import time
import tempfile
import shutil
import uuid
import tarfile
from pathlib import Path
from main import create_sftp_client, upload_file, upload_directory, ensure_remote_dir

PROGRESS_FILE = 'upload_progress.json'
DOWNLOAD_PROGRESS_FILE = 'download_progress.json'
TEMP_DIR = 'temp_downloads'

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

def load_progress():
    """加载上传进度"""
    try:
        with open(PROGRESS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

def save_progress(folder_path, completed_files):
    """保存上传进度"""
    progress = load_progress()
    progress[folder_path] = completed_files
    with open(PROGRESS_FILE, 'w', encoding='utf-8') as f:
        json.dump(progress, f, indent=4, ensure_ascii=False)

def clear_progress(folder_path):
    """清除特定文件夹的上传进度"""
    progress = load_progress()
    if folder_path in progress:
        del progress[folder_path]
        with open(PROGRESS_FILE, 'w', encoding='utf-8') as f:
            json.dump(progress, f, indent=4, ensure_ascii=False)

def get_all_files(folder_path):
    """获取文件夹中的所有文件列表"""
    all_files = []
    for root, _, files in os.walk(folder_path):
        for file in files:
            full_path = os.path.join(root, file)
            rel_path = os.path.relpath(full_path, folder_path)
            all_files.append(rel_path)
    return all_files

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

def upload_folder(folder_path, remote_base_path, resume=True, progress=gr.Progress()):
    """上传文件夹到服务器，支持断点续传"""
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

        # 获取所有文件列表
        all_files = get_all_files(folder_path)
        if not all_files:
            return f"❌ 错误：文件夹 {folder_path} 为空"

        # 加载上次的进度
        completed_files = load_progress().get(folder_path, []) if resume else []
        remaining_files = [f for f in all_files if f not in completed_files]

        if not remaining_files and completed_files:
            return f"✅ 文件夹已完全上传完成，共 {len(completed_files)} 个文件"

        results = []
        if completed_files:
            results.append(f"📝 从上次断点继续上传，已完成 {len(completed_files)} 个文件")

        max_retries = 3
        sftp = None
        transport = None

        try:
            for rel_path in progress.tqdm(remaining_files, desc="正在上传文件"):
                local_path = os.path.join(folder_path, rel_path)
                remote_path = os.path.join(remote_base_path, 
                                         os.path.basename(folder_path), 
                                         rel_path).replace("\\", "/")

                for attempt in range(max_retries):
                    try:
                        if sftp is None or transport is None:
                            sftp, transport = create_sftp_connection(config)

                        # 确保远程目录存在
                        remote_dir = os.path.dirname(remote_path)
                        ensure_remote_dir(sftp, remote_dir)

                        # 上传文件
                        upload_file(sftp, local_path, remote_path)
                        completed_files.append(rel_path)
                        save_progress(folder_path, completed_files)
                        results.append(f"✅ {rel_path} 上传成功")
                        break
                    except Exception as e:
                        if attempt == max_retries - 1:
                            results.append(f"❌ {rel_path} 上传失败：{str(e)}")
                        else:
                            try:
                                if sftp: sftp.close()
                                if transport: transport.close()
                            except:
                                pass
                            sftp = None
                            transport = None
                            time.sleep(2)  # 等待2秒后重试

            if all(f in completed_files for f in all_files):
                clear_progress(folder_path)  # 全部完成后清除进度
                results.append(f"\n✅ 文件夹上传完成！共 {len(all_files)} 个文件")
            
            return "\n".join(results)

        finally:
            try:
                if sftp: sftp.close()
                if transport: transport.close()
            except:
                pass

    except Exception as e:
        return f"❌ 错误：{str(e)}"

def load_download_progress():
    """加载下载进度"""
    try:
        with open(DOWNLOAD_PROGRESS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

def save_download_progress(remote_path, completed_files):
    """保存下载进度"""
    progress = load_download_progress()
    progress[remote_path] = completed_files
    with open(DOWNLOAD_PROGRESS_FILE, 'w', encoding='utf-8') as f:
        json.dump(progress, f, indent=4, ensure_ascii=False)

def clear_download_progress(remote_path):
    """清除特定路径的下载进度"""
    progress = load_download_progress()
    if remote_path in progress:
        del progress[remote_path]
        with open(DOWNLOAD_PROGRESS_FILE, 'w', encoding='utf-8') as f:
            json.dump(progress, f, indent=4, ensure_ascii=False)

def is_dir(sftp, path):
    """检查路径是否为目录"""
    try:
        attrs = sftp.stat(path)
        return str(attrs.st_mode).startswith("4") or str(oct(attrs.st_mode)).startswith("0o4")
    except Exception as e:
        print(f"Error checking if {path} is directory: {str(e)}")
        # 如果不能直接判断，尝试列出目录内容
        try:
            sftp.listdir(path)
            return True  # 如果能列出内容，说明是目录
        except:
            return False

def get_all_remote_files(sftp, remote_path, base_path=None):
    """递归获取远程目录中的所有文件，返回绝对路径和相对路径的映射"""
    if base_path is None:
        base_path = remote_path
    
    all_files = {}  # 使用字典保存文件的绝对路径和相对路径
    all_dirs = []   # 保存所有目录
    
    print(f"Scanning directory: {remote_path}")
    try:
        # 确保当前目录被添加到目录列表
        all_dirs.append(remote_path)
        
        # 列出当前目录下的所有项目
        for item in sftp.listdir(remote_path):
            full_path = os.path.join(remote_path, item).replace("\\", "/")
            
            if is_dir(sftp, full_path):
                # 是目录，添加到目录列表并递归处理
                all_dirs.append(full_path)
                sub_files, sub_dirs = get_all_remote_files(sftp, full_path, base_path)
                all_files.update(sub_files)
                all_dirs.extend(sub_dirs)
            else:
                # 是文件，添加到文件字典
                rel_path = os.path.relpath(full_path, base_path)
                all_files[full_path] = rel_path
    except Exception as e:
        print(f"Error listing directory {remote_path}: {str(e)}")
    
    return all_files, all_dirs

def create_all_local_dirs(local_base_path, all_remote_dirs, remote_base_path):
    """创建所有本地目录"""
    for remote_dir in all_remote_dirs:
        try:
            # 计算相对路径
            rel_path = os.path.relpath(remote_dir, remote_base_path)
            
            # 跳过根目录
            if rel_path == ".":
                continue
                
            # 创建本地目录
            local_dir = os.path.join(local_base_path, rel_path)
            os.makedirs(local_dir, exist_ok=True)
            print(f"Created directory: {local_dir}")
        except Exception as e:
            print(f"Error creating directory for {remote_dir}: {str(e)}")

def download_folder(remote_path, local_path, resume=True, progress=gr.Progress()):
    """从服务器下载文件夹"""
    try:
        if not remote_path:
            return "请输入要下载的远程文件夹路径！"
            
        if not local_path:
            return "请输入本地保存路径！"
            
        config = load_config()
        if not config["host"]:
            return "请先配置服务器信息！"

        # 获取远程文件夹名称
        remote_folder_name = os.path.basename(remote_path.rstrip("/"))
        # 创建完整的本地保存路径（包含远程文件夹名）
        full_local_path = os.path.join(local_path, remote_folder_name)
        
        # 创建主文件夹
        os.makedirs(full_local_path, exist_ok=True)
        print(f"Main folder created: {full_local_path}")

        results = []
        sftp = None
        transport = None

        try:
            sftp, transport = create_sftp_connection(config)
            
            # 检查远程路径是否存在
            try:
                sftp.listdir(remote_path)
            except Exception as e:
                return f"❌ 错误：无法访问远程路径 {remote_path}：{str(e)}"
            
            # 获取所有远程文件和目录
            try:
                print(f"Scanning remote directory structure: {remote_path}")
                remote_files_map, remote_dirs = get_all_remote_files(sftp, remote_path)
                
                if not remote_files_map:
                    return f"❌ 错误：远程目录 {remote_path} 中没有找到文件"
                
                print(f"Found {len(remote_files_map)} files and {len(remote_dirs)} directories")
                
                # 创建所有本地目录
                create_all_local_dirs(full_local_path, remote_dirs, remote_path)
                
            except Exception as e:
                return f"❌ 错误：扫描远程目录 {remote_path} 时出错：{str(e)}"

            # 加载断点续传进度
            completed_files = load_download_progress().get(remote_path, []) if resume else []
            
            # 过滤出未完成的文件
            remaining_files = {remote_path: rel_path for remote_path, rel_path in remote_files_map.items() 
                              if remote_path not in completed_files}

            if not remaining_files and completed_files:
                return f"✅ 文件夹已完全下载完成，共 {len(completed_files)} 个文件"

            if completed_files:
                results.append(f"📝 从上次断点继续下载，已完成 {len(completed_files)} 个文件")

            # 下载文件
            max_retries = 3
            
            for remote_file_path, rel_path in progress.tqdm(remaining_files.items(), desc="正在下载文件"):
                # 构建本地文件路径
                local_file_path = os.path.join(full_local_path, rel_path)
                print(f"Downloading: {rel_path} -> {local_file_path}")

                for attempt in range(max_retries):
                    try:
                        if sftp is None or transport is None:
                            sftp, transport = create_sftp_connection(config)

                        # 确保本地目录存在
                        os.makedirs(os.path.dirname(local_file_path), exist_ok=True)
                        
                        # 下载文件
                        sftp.get(remote_file_path, local_file_path)
                        completed_files.append(remote_file_path)
                        save_download_progress(remote_path, completed_files)
                        results.append(f"✅ {rel_path} 下载成功")
                        break
                    except Exception as e:
                        print(f"Download attempt {attempt+1} failed for {remote_file_path}: {str(e)}")
                        if attempt == max_retries - 1:
                            results.append(f"❌ {rel_path} 下载失败：{str(e)}")
                        else:
                            try:
                                if sftp: sftp.close()
                                if transport: transport.close()
                            except:
                                pass
                            sftp = None
                            transport = None
                            time.sleep(2)  # 等待2秒后重试

            if len(completed_files) == len(remote_files_map):
                clear_download_progress(remote_path)  # 全部完成后清除进度
                results.append(f"\n✅ 文件夹下载完成！共 {len(remote_files_map)} 个文件")
            
            return "\n".join(results)

        finally:
            try:
                if sftp: sftp.close()
                if transport: transport.close()
            except:
                pass

    except Exception as e:
        return f"❌ 错误：{str(e)}"

def create_remote_archive(sftp, transport, remote_path):
    """在远程服务器上创建压缩文件"""
    try:
        # 获取远程文件夹名
        remote_folder_name = os.path.basename(remote_path.rstrip("/"))
        # 生成唯一的压缩文件名
        archive_name = f"{remote_folder_name}_{uuid.uuid4().hex[:8]}.tar.gz"
        archive_path = f"/tmp/{archive_name}"
        
        # 在服务器上执行压缩命令
        ssh = transport.open_channel("session")
        # 进入父目录并执行压缩命令
        parent_dir = os.path.dirname(remote_path)
        target_dir = os.path.basename(remote_path)
        compress_cmd = f"cd {parent_dir} && tar -czf {archive_path} {target_dir} && echo 'Compression completed: {archive_path}'"
        
        ssh.exec_command(compress_cmd)
        
        # 等待命令完成
        exit_status = ssh.recv_exit_status()
        if exit_status != 0:
            error_msg = ssh.recv_stderr(4096).decode()
            ssh.close()
            raise Exception(f"压缩失败，错误码: {exit_status}, 信息: {error_msg}")
        
        ssh.close()
        return archive_path
    except Exception as e:
        raise Exception(f"创建远程压缩文件失败: {str(e)}")

def download_compressed_folder(remote_path, local_path, progress=gr.Progress()):
    """压缩后下载文件夹"""
    try:
        if not remote_path:
            return "请输入要下载的远程文件夹路径！"
            
        if not local_path:
            return "请输入本地保存路径！"
            
        config = load_config()
        if not config["host"]:
            return "请先配置服务器信息！"

        # 安全地更新进度
        def update_progress(value, desc=None):
            try:
                if progress is not None:
                    progress(value, desc)
            except Exception as e:
                print(f"更新进度时出错 (忽略): {str(e)}")

        # 获取远程文件夹名称
        remote_folder_name = os.path.basename(remote_path.rstrip("/"))
        
        # 确保本地目录存在
        os.makedirs(local_path, exist_ok=True)
        
        # 确保临时目录存在
        os.makedirs(TEMP_DIR, exist_ok=True)
        
        # 生成临时文件路径
        local_archive_path = os.path.join(TEMP_DIR, f"{remote_folder_name}.tar.gz")
        
        results = []
        sftp = None
        transport = None

        try:
            update_progress(0, "正在连接服务器...")
            sftp, transport = create_sftp_connection(config)
            
            # 检查远程路径是否存在
            try:
                sftp.listdir(remote_path)
            except Exception as e:
                return f"❌ 错误：无法访问远程路径 {remote_path}：{str(e)}"
            
            # 在服务器上创建压缩文件
            update_progress(0.1, "正在服务器上压缩文件夹...")
            try:
                remote_archive_path = create_remote_archive(sftp, transport, remote_path)
                results.append(f"✓ 服务器上压缩完成: {remote_archive_path}")
            except Exception as e:
                return f"❌ 压缩失败：{str(e)}"
            
            # 下载压缩文件
            update_progress(0.4, "正在下载压缩文件...")
            try:
                # 获取文件大小
                remote_size = sftp.stat(remote_archive_path).st_size
                downloaded = 0
                
                # 创建进度回调函数
                def update_download_progress(bytes_transferred, total_bytes):
                    nonlocal downloaded
                    new_downloaded = bytes_transferred
                    if new_downloaded > downloaded:
                        downloaded = new_downloaded
                        percent = 0.4 + (downloaded / remote_size) * 0.5
                        try:
                            update_progress(min(0.9, percent), f"正在下载：{downloaded / 1024 / 1024:.2f} MB / {remote_size / 1024 / 1024:.2f} MB")
                        except Exception as e:
                            print(f"更新下载进度时出错 (忽略): {str(e)}")
                
                # 下载文件
                sftp.get(remote_archive_path, local_archive_path, callback=update_download_progress)
                results.append(f"✓ 压缩文件下载完成: {local_archive_path}")
            except Exception as e:
                return f"❌ 下载压缩文件失败：{str(e)}"
            
            # 清理远程临时文件
            try:
                sftp.remove(remote_archive_path)
                results.append("✓ 已清理远程临时文件")
            except Exception as e:
                results.append(f"⚠️ 清理远程临时文件失败：{str(e)}")
            
            # 解压文件
            update_progress(0.9, "正在解压文件...")
            try:
                # 生成解压目标路径
                extract_path = os.path.join(local_path, remote_folder_name)
                
                # 如果目标路径已存在，先删除
                if os.path.exists(extract_path):
                    if os.path.isdir(extract_path):
                        shutil.rmtree(extract_path)
                    else:
                        os.remove(extract_path)
                
                # 解压文件
                shutil.unpack_archive(local_archive_path, local_path)
                results.append(f"✓ 文件解压完成: {extract_path}")
            except Exception as e:
                return f"❌ 解压文件失败：{str(e)}"
            
            # 清理本地临时文件
            try:
                os.remove(local_archive_path)
                results.append("✓ 已清理本地临时文件")
            except Exception as e:
                results.append(f"⚠️ 清理本地临时文件失败：{str(e)}")
            
            update_progress(1.0, "下载完成！")
            results.append(f"\n✅ 文件夹下载完成！保存在: {os.path.join(local_path, remote_folder_name)}")
            
            return "\n".join(results)

        finally:
            try:
                if sftp: sftp.close()
                if transport: transport.close()
            except:
                pass

    except Exception as e:
        return f"❌ 错误：{str(e)}"

def create_local_archive(folder_path, progress=None):
    """创建本地压缩文件"""
    try:
        # 确保临时目录存在
        os.makedirs(TEMP_DIR, exist_ok=True)
        
        # 获取文件夹名称
        folder_name = os.path.basename(folder_path)
        print(f"处理文件夹: {folder_path}, 文件夹名称: {folder_name}")
        
        # 检查文件夹是否为空
        if not os.path.exists(folder_path):
            raise Exception(f"文件夹不存在: {folder_path}")
            
        if not os.path.isdir(folder_path):
            raise Exception(f"路径不是文件夹: {folder_path}")
        
        # 检查文件夹是否为空
        has_files = False
        for root, dirs, files in os.walk(folder_path):
            if files:
                has_files = True
                break
                
        if not has_files:
            raise Exception(f"文件夹为空: {folder_path}")
        
        # 生成压缩文件路径
        archive_path = os.path.join(TEMP_DIR, f"{folder_name}_{uuid.uuid4().hex[:8]}.tar.gz")
        print(f"压缩文件路径: {archive_path}")
        
        # 安全地更新进度
        def update_progress(value, desc=None):
            try:
                if progress is not None:
                    progress(value, desc)
            except Exception as e:
                print(f"更新进度时出错 (忽略): {str(e)}")
        
        update_progress(0.1, "正在创建压缩文件...")
            
        # 获取文件夹中的所有文件
        all_files = []
        total_size = 0
        for root, _, files in os.walk(folder_path):
            print(f"扫描目录: {root}")
            for file in files:
                try:
                    file_path = os.path.join(root, file)
                    if os.path.exists(file_path):  # 确保文件仍然存在
                        file_size = os.path.getsize(file_path)
                        all_files.append((file_path, file_size))
                        total_size += file_size
                        print(f"添加文件: {file_path}, 大小: {file_size}")
                except Exception as e:
                    print(f"警告：处理文件 {file} 时出错: {str(e)}")
                    continue
        
        if not all_files:
            raise Exception("没有找到可以压缩的文件")
        
        print(f"共找到 {len(all_files)} 个文件，总大小: {total_size} 字节")
        
        # 创建压缩文件
        with tarfile.open(archive_path, "w:gz") as tar:
            processed_size = 0
            for idx, (file_path, file_size) in enumerate(all_files):
                try:
                    if os.path.exists(file_path):  # 再次检查文件是否存在
                        # 确保文件相对路径计算正确
                        try:
                            # 使用正确的方式计算相对路径，避免列表索引越界
                            parent_dir = os.path.dirname(folder_path)
                            print(f"计算相对路径: 文件={file_path}, 父目录={parent_dir}")
                            
                            # 直接使用os.path.relpath并捕获可能的错误
                            try:
                                rel_path = os.path.relpath(file_path, parent_dir)
                                print(f"计算的相对路径: {rel_path}")
                            except ValueError as e:
                                # 如果relpath失败，使用替代方法
                                print(f"计算相对路径失败: {str(e)}")
                                # 直接从文件路径中移除文件夹路径前缀
                                rel_path = file_path[len(folder_path):].lstrip(os.sep)
                                print(f"使用替代方法计算的相对路径: {rel_path}")
                            
                            # 构建压缩包中的目标路径
                            arcname = os.path.join(folder_name, rel_path)
                            print(f"归档名称: {arcname}")
                            
                            # 添加到压缩包
                            tar.add(file_path, arcname=arcname)
                            
                            # 安全地更新进度
                            processed_size += file_size
                            percent = 0.1 + (processed_size / total_size) * 0.4
                            update_progress(min(0.5, percent), f"正在压缩：{processed_size/1024/1024:.2f} MB / {total_size/1024/1024:.2f} MB")
                        except Exception as e:
                            print(f"计算文件 {file_path} 的相对路径时出错: {str(e)}")
                            # 使用文件名作为后备选项
                            tar.add(file_path, arcname=os.path.basename(file_path))
                            print(f"使用文件名 {os.path.basename(file_path)} 作为备选添加文件")
                except Exception as e:
                    print(f"警告：压缩文件 {file_path} 时出错: {str(e)}")
                    continue
        
        # 检查压缩文件是否成功创建
        if not os.path.exists(archive_path) or os.path.getsize(archive_path) == 0:
            raise Exception("压缩文件创建失败或为空")
            
        print(f"压缩完成: {archive_path}")
        return archive_path
    except Exception as e:
        print(f"创建压缩文件异常: {str(e)}")
        import traceback
        traceback.print_exc()
        raise Exception(f"创建本地压缩文件失败: {str(e)}")

def extract_remote_archive(sftp, transport, remote_archive_path, remote_target_dir):
    """在远程服务器上解压文件"""
    try:
        # 确保远程目标目录存在
        ensure_remote_dir(sftp, remote_target_dir)
        
        # 在服务器上执行解压命令
        ssh = transport.open_channel("session")
        extract_cmd = f"tar -xzf {remote_archive_path} -C {remote_target_dir} && echo 'Extraction completed'"
        
        ssh.exec_command(extract_cmd)
        
        # 等待命令完成
        exit_status = ssh.recv_exit_status()
        if exit_status != 0:
            error_msg = ssh.recv_stderr(4096).decode()
            ssh.close()
            raise Exception(f"解压失败，错误码: {exit_status}, 信息: {error_msg}")
        
        ssh.close()
        return True
    except Exception as e:
        raise Exception(f"在服务器上解压文件失败: {str(e)}")

def upload_compressed_folder(folder_path, remote_path, progress=gr.Progress()):
    """压缩后上传文件夹"""
    try:
        if not folder_path:
            return "请选择要上传的文件夹！"
            
        if not remote_path:
            return "请输入远程目录路径！"
            
        if not os.path.exists(folder_path):
            return f"❌ 错误：文件夹 {folder_path} 不存在"
            
        if not os.path.isdir(folder_path):
            return f"❌ 错误：{folder_path} 不是一个文件夹"
            
        config = load_config()
        if not config["host"]:
            return "请先配置服务器信息！"
        
        # 安全地更新进度
        def update_progress(value, desc=None):
            try:
                if progress is not None:
                    progress(value, desc)
            except Exception as e:
                print(f"更新进度时出错 (忽略): {str(e)}")
        
        results = []
        local_archive_path = None
        remote_archive_path = None
        sftp = None
        transport = None
        
        try:
            # 创建本地压缩文件
            try:
                local_archive_path = create_local_archive(folder_path, progress)
                results.append(f"✓ 本地压缩完成: {local_archive_path}")
            except Exception as e:
                return f"❌ 压缩失败：{str(e)}"
            
            # 连接服务器
            update_progress(0.5, "正在连接服务器...")
            sftp, transport = create_sftp_connection(config)
            
            # 上传压缩文件
            update_progress(0.6, "正在上传压缩文件...")
            try:
                # 生成远程临时文件路径
                remote_archive_name = os.path.basename(local_archive_path)
                remote_archive_path = f"/tmp/{remote_archive_name}"
                
                # 获取文件大小
                local_size = os.path.getsize(local_archive_path)
                uploaded = 0
                
                # 创建进度回调函数
                def update_upload_progress(bytes_transferred, total_bytes):
                    nonlocal uploaded
                    new_uploaded = bytes_transferred
                    if new_uploaded > uploaded:
                        uploaded = new_uploaded
                        percent = 0.6 + (uploaded / local_size) * 0.3
                        try:
                            update_progress(min(0.9, percent), f"正在上传：{uploaded/1024/1024:.2f} MB / {local_size/1024/1024:.2f} MB")
                        except Exception as e:
                            print(f"更新上传进度时出错 (忽略): {str(e)}")
                
                # 上传文件
                sftp.put(local_archive_path, remote_archive_path, callback=update_upload_progress)
                results.append(f"✓ 压缩文件上传完成: {remote_archive_path}")
            except Exception as e:
                return f"❌ 上传压缩文件失败：{str(e)}"
            
            # 在服务器上解压文件
            update_progress(0.9, "正在服务器上解压文件...")
            try:
                extract_remote_archive(sftp, transport, remote_archive_path, remote_path)
                results.append(f"✓ 远程解压完成: {remote_path}")
            except Exception as e:
                return f"❌ 解压失败：{str(e)}"
            
            # 清理临时文件
            try:
                # 清理远程临时文件
                sftp.remove(remote_archive_path)
                results.append("✓ 已清理远程临时文件")
                
                # 清理本地临时文件
                os.remove(local_archive_path)
                results.append("✓ 已清理本地临时文件")
            except Exception as e:
                results.append(f"⚠️ 清理临时文件失败：{str(e)}")
            
            update_progress(1.0, "上传完成！")
            results.append(f"\n✅ 文件夹上传完成！")
            
            return "\n".join(results)
            
        finally:
            try:
                if sftp: sftp.close()
                if transport: transport.close()
            except:
                pass
            
    except Exception as e:
        return f"❌ 错误：{str(e)}"

# 加载现有配置
current_config = load_config()

# 创建 Gradio 界面
with gr.Blocks(title="AutoDL 数据传输工具", theme=gr.themes.Soft()) as app:
    gr.Markdown("""
    # 🚀 AutoDL 数据传输工具
    
    这是一个用于本地与 AutoDL 服务器之间传输数据的工具。使用 SFTP 协议，支持安全的文件传输。
    支持双向传输，可以上传本地文件到服务器，也可以从服务器下载文件到本地。
    支持断点续传功能，传输中断后可以从上次的位置继续。
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
    
    with gr.Tab("上传文件"):
        with gr.Row():
            with gr.Column():
                files = gr.File(label="选择文件", file_count="multiple")
                remote_path_files = gr.Textbox(label="远程目录路径", placeholder="例如：/root/数据", value="/root")
                upload_files_btn = gr.Button("📤 上传文件", variant="primary")
                files_output = gr.Textbox(label="上传状态", interactive=False)
    
    with gr.Tab("上传文件夹"):
        with gr.Row():
            with gr.Column():
                folder = gr.Textbox(label="文件夹路径", placeholder="输入本地文件夹的完整路径")
                remote_path_folder = gr.Textbox(label="远程目录路径", placeholder="例如：/root/数据集", value="/root")
                with gr.Row():
                    upload_type = gr.Radio(
                        label="上传方式",
                        choices=["常规上传", "压缩后上传(推荐)"],
                        value="压缩后上传(推荐)"
                    )
                    resume_checkbox = gr.Checkbox(
                        label="断点续传",
                        value=True,
                        info="从上次中断的位置继续上传",
                        visible=False
                    )
                
                upload_folder_btn = gr.Button("📁 上传文件夹", variant="primary")
                folder_output = gr.Textbox(label="上传状态", interactive=False, lines=10)
    
    with gr.Tab("从服务器下载"):
        with gr.Row():
            with gr.Column():
                remote_folder = gr.Textbox(
                    label="远程文件夹路径",
                    placeholder="例如：/root/数据集",
                    value="/root"
                )
                local_save_path = gr.Textbox(
                    label="本地保存路径",
                    placeholder="例如：D:/下载的数据集",
                    value=str(Path.home() / "Downloads" / "autodl_downloads")
                )
                with gr.Row():
                    download_type = gr.Radio(
                        label="下载方式",
                        choices=["常规下载", "压缩后下载(推荐)"],
                        value="压缩后下载(推荐)"
                    )
                    download_resume_checkbox = gr.Checkbox(
                        label="断点续传",
                        value=True,
                        info="从上次中断的位置继续下载",
                        visible=False
                    )
                
                download_btn = gr.Button("⬇️ 下载文件夹", variant="primary")
                download_output = gr.Textbox(
                    label="下载状态",
                    interactive=False,
                    lines=10
                )
    
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
    
    # 根据选择的上传方式显示或隐藏断点续传选项
    upload_type.change(
        lambda x: gr.update(visible=(x == "常规上传")),
        inputs=[upload_type],
        outputs=[resume_checkbox]
    )
    
    # 处理上传文件夹
    def handle_upload_folder(folder_path, remote_path, upload_type, resume):
        if upload_type == "压缩后上传(推荐)":
            return upload_compressed_folder(folder_path, remote_path)
        else:
            return upload_folder(folder_path, remote_path, resume)
    
    upload_folder_btn.click(
        handle_upload_folder,
        inputs=[folder, remote_path_folder, upload_type, resume_checkbox],
        outputs=folder_output
    )
    
    # 根据选择的下载方式显示或隐藏断点续传选项
    download_type.change(
        lambda x: gr.update(visible=(x == "常规下载")),
        inputs=[download_type],
        outputs=[download_resume_checkbox]
    )
    
    # 下载按钮处理
    def handle_download(remote_path, local_path, download_type, resume):
        if download_type == "压缩后下载(推荐)":
            return download_compressed_folder(remote_path, local_path)
        else:
            return download_folder(remote_path, local_path, resume)
    
    download_btn.click(
        handle_download,
        inputs=[remote_folder, local_save_path, download_type, download_resume_checkbox],
        outputs=download_output
    )

if __name__ == "__main__":
    app.launch(share=False, server_name="127.0.0.1", server_port=7860) 