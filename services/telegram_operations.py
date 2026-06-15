"""Telegram 批量操作辅助模块。

将异步 TG 操作（删消息/改标题/删频道）封装为 Task 并提交到 TaskManager。
"""
from loguru import logger
from core.task_types import Task


def batch_delete_tg_messages(msg_list, task_manager):
    """批量删除 Telegram 消息。"""
    if not msg_list:
        return
    logger.info(f"[TG] 批量删除消息: {len(msg_list)} 条")

    async def delete_coro(client, signals):
        for chat_id, msg_id in msg_list:
            try:
                await client.delete_messages(chat_id, msg_id)
            except Exception as e:
                logger.error(f"批量删除消息失败: {e}")

    task = Task(
        task_id=f"del_msgs_{hash(tuple(msg_list))}",
        task_type="delete_messages",
        coro=delete_coro,
        description=f"删除 {len(msg_list)} 条消息"
    )
    task_manager.submit_task(task)


def batch_edit_tg_captions(edit_list, task_manager):
    """批量修改 Telegram 消息 caption。"""
    if not edit_list:
        return
    logger.info(f"[TG] 批量修改Caption: {len(edit_list)} 条")

    async def edit_coro(client, signals):
        for chat_id, msg_id, new_caption in edit_list:
            try:
                await client.edit_message(chat_id, msg_id, text=new_caption)
            except Exception as e:
                logger.error(f"批量修改Caption失败: {e}")

    task = Task(
        task_id=f"edit_cap_{hash(tuple(edit_list))}",
        task_type="edit_captions",
        coro=edit_coro,
        description=f"修改 {len(edit_list)} 条 caption"
    )
    task_manager.submit_task(task)


def batch_edit_tg_channel(channel_id, new_title, task_manager):
    """修改 Telegram 频道标题。"""
    if not channel_id:
        return
    logger.info(f"[TG] 修改频道标题: channel={channel_id}, title={new_title}")

    async def edit_coro(client, signals):
        from telethon.tl.functions.channels import EditTitleRequest
        from telethon.tl.types import PeerChannel
        entity = await client.get_input_entity(PeerChannel(int(channel_id)))
        await client(EditTitleRequest(channel=entity, title=new_title))

    task = Task(
        task_id=f"edit_channel_{channel_id}",
        task_type="edit_channel",
        coro=edit_coro,
        description=f"修改频道标题为 {new_title}"
    )
    task_manager.submit_task(task)


def delete_tg_channel(channel_id, task_manager):
    """删除（离开）Telegram 频道。"""
    async def delete_coro(client, signals):
        from telethon.tl.functions.channels import DeleteChannelRequest
        try:
            entity = await client.get_input_entity(int(channel_id))
            await client(DeleteChannelRequest(channel=entity))
            logger.info(f"[TG] 频道 {channel_id} 已删除")
        except Exception as e:
            logger.error(f"删除频道失败: {e}")

    task = Task(
        task_id=f"del_chan_{channel_id}",
        task_type="delete_channel",
        coro=delete_coro,
        description=f"删除频道 {channel_id}"
    )
    task_manager.submit_task(task)
