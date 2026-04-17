"""Foundation sync service package.

注意：这里保持轻量，避免在包导入阶段触发重量级依赖（例如 DAOFactory），
从而引入循环导入。
"""

__all__: list[str] = []
