import os
import json
import argparse
from pathlib import Path
import paramiko
from tqdm import tqdm

def load_config():
    """加载配置文件"""
    try:
        with open('config.json', 'r', encoding='utf-8') as f:
            config = json.load(f)
        
        # 验证配置是否完整
        required_fields = ['host', 'port', 'username', 'password']
        for field in required_fields:
            if field not in config:
                raise ValueError(f"配置文件中缺少 {field} 字段")
        
        print(f"正在连接到服务器: {config['username']}@{config['host']}:{config['port']}")
        return config
    except FileNotFoundError:
        raise FileNotFoundError("找不到配置文件 config.json")
    except json.JSONDecodeError:
        raise ValueError("配置文件格式错误，请确保是有效的 JSON 格式")

def create_sftp_client(config):
    """创建 SFTP 客户端连接"""
    try:
        print("正在创建 SSH 传输通道...")
        transport = paramiko.Transport((config['host'], config['port']))
        print("正在尝试身份验证...")
        transport.connect(username=config['username'], password=config['password'])
        print("身份验证成功，正在创建 SFTP 客户端...")
        sftp = paramiko.SFTPClient.from_transport(transport)
        return sftp, transport
    except Exception as e:
        print(f"详细错误信息: {str(e)}")
        if "Authentication failed" in str(e):
            raise Exception(f"身份验证失败，请检查用户名和密码是否正确")
        raise Exception(f"连接到 AutoDL 服务器失败: {str(e)}")

def upload_file(sftp, local_path, remote_path):
    """上传单个文件到远程服务器"""
    try:
        # 获取文件大小
        file_size = os.path.getsize(local_path)
        
        # 创建进度条
        with tqdm(total=file_size, unit='B', unit_scale=True, desc=f"上传 {os.path.basename(local_path)}") as pbar:
            sftp.put(local_path, remote_path, callback=lambda sent, total: pbar.update(sent - pbar.n))
            
    except Exception as e:
        raise Exception(f"文件上传失败: {str(e)}")

def ensure_remote_dir(sftp, remote_path):
    """确保远程目录存在，如果不存在则创建"""
    try:
        sftp.stat(remote_path)
    except IOError:
        print(f"创建远程目录: {remote_path}")
        current_path = ""
        for part in remote_path.split("/"):
            if not part:
                continue
            current_path += "/" + part
            try:
                sftp.stat(current_path)
            except IOError:
                sftp.mkdir(current_path)

def upload_directory(sftp, local_dir, remote_dir):
    """递归上传整个目录"""
    try:
        # 确保远程目录存在
        ensure_remote_dir(sftp, remote_dir)
        
        # 遍历本地目录
        for root, dirs, files in os.walk(local_dir):
            # 计算相对路径
            rel_path = os.path.relpath(root, local_dir)
            if rel_path == ".":
                rel_path = ""
            
            # 创建远程子目录
            for dir_name in dirs:
                local_path = os.path.join(root, dir_name)
                remote_path = os.path.join(remote_dir, rel_path, dir_name).replace("\\", "/")
                ensure_remote_dir(sftp, remote_path)
            
            # 上传文件
            for file_name in files:
                local_path = os.path.join(root, file_name)
                remote_path = os.path.join(remote_dir, rel_path, file_name).replace("\\", "/")
                upload_file(sftp, local_path, remote_path)
                
    except Exception as e:
        raise Exception(f"目录上传失败: {str(e)}")

def main():
    parser = argparse.ArgumentParser(description="将本地文件或目录上传到 AutoDL 服务器")
    parser.add_argument('--local_path', required=True, help="本地文件或目录路径")
    parser.add_argument('--remote_path', required=True, help="远程目标路径")
    args = parser.parse_args()

    try:
        # 检查本地路径是否存在
        if not os.path.exists(args.local_path):
            raise FileNotFoundError(f"本地路径不存在: {args.local_path}")

        # 加载配置
        config = load_config()
        
        # 创建 SFTP 客户端
        sftp, transport = create_sftp_client(config)
        
        try:
            # 判断是文件还是目录
            if os.path.isfile(args.local_path):
                print(f"正在上传文件: {args.local_path}")
                upload_file(sftp, args.local_path, args.remote_path)
            else:
                print(f"正在上传目录: {args.local_path}")
                upload_directory(sftp, args.local_path, args.remote_path)
            
            print(f"\n传输完成！")
            
        finally:
            # 关闭连接
            sftp.close()
            transport.close()
            
    except Exception as e:
        print(f"错误: {str(e)}")
        return 1

    return 0

if __name__ == "__main__":
    exit(main()) 