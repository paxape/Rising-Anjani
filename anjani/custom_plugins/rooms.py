"""Anjani example-plugin"""
# Copyright (C) 2020 - 2023  UserbotIndo Team, <https://github.com/userbotindo.git>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

from io import BytesIO
from typing import ClassVar, Optional
import asyncio
from typing import Any, ClassVar, MutableMapping, TypedDict
from collections import defaultdict

from pyrogram.types import CallbackQuery, Message, ForumTopic, InlineKeyboardButton, InlineKeyboardMarkup

from anjani import command, filters, listener, plugin, util

DELETE_RESPONSE_TIME: float = 15

class WriterInfo(TypedDict):
    writer_id: int
    message_id: int

class RoomInfo(TypedDict):
    owner_id: int
    description_id: int
    writers: list[WriterInfo]


class Rooms(plugin.Plugin):
    name: ClassVar[str] = "rooms"
    disabled: ClassVar[bool] = False
    helpable: ClassVar[bool] = True

    db: util.db.AsyncCollection
    rooms: MutableMapping[int, MutableMapping[int, RoomInfo]] = defaultdict(dict) # {chat_id: {thread_id: roomInfo}}

    async def on_load(self) -> None:
        self.db = self.bot.db.get_collection("ROOMS")

    async def on_chat_migrate(self, message: Message) -> None:
        self.log.info("Migrating chat...")
        new_chat = message.chat.id
        old_chat = message.migrate_from_chat_id

        await self.db.update_one(
            {"chat_id": old_chat},
            {"$set": {"chat_id": new_chat}},
        )

    async def on_plugin_backup(self, chat_id: int) -> MutableMapping[str, Any]:
        """Dispatched when /backup command is Called"""
        self.log.info("Backing up data plugin: %s", self.name)
        data = await self.db.find_one({"chat_id": chat_id}, {"_id": False})
        if not data:
            return {}

        return {self.name: data}

    async def on_plugin_restore(self, chat_id: int, data: MutableMapping[str, Any]) -> None:
        """Dispatched when /restore command is Called"""
        self.log.info("Restoring data plugin: %s", self.name)
        await self.db.update_one({"chat_id": chat_id}, {"$set": data[self.name]}, upsert=True)

    async def get_room_info(self, chat_id: int, thread_id: int) -> RoomInfo | None:
        if self.rooms[chat_id].get(thread_id):
            return self.rooms[chat_id][thread_id]
        else:
            data = await self.db.find_one(
                {"chat_id": chat_id, f"topics.{thread_id}": {"$exists": True}}, {f"topics.{thread_id}": 1}
            )
            if data:
                room_info: RoomInfo = data["topics"][str(thread_id)]
                self.rooms[chat_id][thread_id] = room_info
                return room_info
            else:
                return

    async def update_db_writer(self, chat_id: int, thread_id: int, writer_id: int, message_id: int, update: bool):
        if update:
            await self.db.update_one(
                {
                    "chat_id": chat_id,
                    f"topics.{thread_id}.writers.writer_id": writer_id,
                },
                {
                    "$set": {
                    f"topics.{thread_id}.writers.$.message_id": message_id
                    }
                }
            )
        else:
            await self.db.update_one(
                {"chat_id": chat_id},
                {
                    "$push": {
                        f"topics.{thread_id}.writers": {
                            "writer_id": writer_id,
                            "message_id": message_id
                        }
                    }
                }
            )

    @listener.priority(120)
    @listener.filters(filters.group) # Filter Listener only on group chats
    async def on_message(self, message: Message) -> None:
        room_info: RoomInfo = await self.get_room_info(message.chat.id, message.message_thread_id)
        if not room_info:
            return
        if not room_info.get("writers"):
            room_info["writers"] = list()

        if (message.text is not None and message.text.startswith("/")) or message.from_user.is_bot: # Not a posting
            await self.bot.client.delete_messages(message.chat.id, message.id)
        else:
            writer_info: WriterInfo = next((w for w in room_info["writers"] if w["writer_id"] == message.from_user.id), None)
            if writer_info:
                wm: Message = await self.bot.client.get_messages(message.chat.id, writer_info["message_id"])
                if wm.message_thread_id: # User already posted --> send backup as private message and delete
                    async def send_backup_message():
                        try:
                            backup = BytesIO(message.text.encode())
                            backup.name = f"backup_{message.from_user.username}.txt"
                            await self.bot.client.send_document(message.chat.id, backup, caption=await self.text(message.chat.id, "rooms-backup-message", username=message.from_user.mention), disable_notification=True)
                        except Exception as err:
                            self.log.info(f"Cannot send deleted message to user {message.from_user.username}. ({type(err).__name__}: {str(err)})")

                    await asyncio.gather(
                            message.delete(),
                            send_backup_message()
                    )
                    return
                else: # Post of user not found --> save new ID of new post
                    writer_info["message_id"] = message.id
            else: # new writer
                room_info["writers"].append(WriterInfo(writer_id=message.from_user.id, message_id=message.id))

            await self.update_db_writer(chat_id=message.chat.id, thread_id=message.message_thread_id, writer_id=message.from_user.id, message_id=message.id, update=(writer_info is not None))


    async def cmd_newroom(self, ctx: command.Context) -> Optional[str]:
        """Create room"""

        chat_id = ctx.chat.id
        if not ctx.chat.is_forum:
            await ctx.respond(await self.text(chat_id, "rooms-non-topic"), delete_after=DELETE_RESPONSE_TIME)
            return

        name = ctx.input
        if not name:
            await ctx.respond(await self.text(chat_id, "rooms-name-missing"), delete_after=DELETE_RESPONSE_TIME)
            return

        new_room: ForumTopic = await self.bot.client.create_forum_topic(chat_id, name, None, 5370870893004203704)
        room_description = await self.bot.client.send_message(chat_id, await self.text(chat_id, "rooms-description", room_name = new_room.title, room_desc = await self.text(chat_id, "rooms-standard-description"), username=ctx.author.username), message_thread_id=new_room.id)

        room_info = RoomInfo(owner_id=ctx.author.id, description_id=room_description.id)
        await asyncio.gather(
            self.db.update_one(
                {"chat_id": chat_id},
                {
                    "$set": {
                        "chat_name": ctx.chat.title,
                        f"topics.{str(new_room.id)}": room_info,
                    }
                },
                upsert=True,
            ),
            ctx.respond(await self.text(chat_id, "rooms-created"), delete_after=DELETE_RESPONSE_TIME),
        )

        self.rooms[chat_id][new_room.id] = room_info

    async def cmd_roomname(self, ctx: command.Context) -> Optional[str]:
        """Rename room"""

        if not ctx.chat.is_forum:
            await ctx.respond(await self.text(ctx.chat.id, "rooms-non-topic"), delete_after=DELETE_RESPONSE_TIME)
            return

        room_info: RoomInfo = await self.get_room_info(ctx.chat.id, ctx.msg.message_thread_id)
        if not room_info:
            await ctx.respond(await self.text(ctx.chat.id, "rooms-non-room"), delete_after=DELETE_RESPONSE_TIME)
            return

        if room_info["owner_id"] != ctx.author.id:
            await ctx.respond(await self.text(ctx.chat.id, "error-no-rights"), delete_after=DELETE_RESPONSE_TIME)
            return

        name = ctx.input
        if not name:
            await ctx.respond(await self.text(ctx.chat.id, "rooms-name-missing"), delete_after=DELETE_RESPONSE_TIME)
            return

        await self.bot.client.edit_forum_topic(ctx.chat.id, ctx.msg.message_thread_id, name)

    async def cmd_roomdesc(self, ctx: command.Context) -> Optional[str]:
        """Change room description"""

        chat_id = ctx.chat.id
        if not ctx.chat.is_forum:
            await ctx.respond(await self.text(chat_id, "rooms-non-topic"), delete_after=DELETE_RESPONSE_TIME)
            return

        room_info: RoomInfo = await self.get_room_info(ctx.chat.id, ctx.msg.message_thread_id)
        if not room_info:
            await ctx.respond(await self.text(chat_id, "rooms-non-room"), delete_after=DELETE_RESPONSE_TIME)
            return

        if room_info["owner_id"] != ctx.author.id:
            await ctx.respond(await self.text(chat_id, "error-no-rights"), delete_after=DELETE_RESPONSE_TIME)
            return

        desc = ctx.input
        if not desc:
            await ctx.respond(await self.text(ctx.chat.id, "rooms-desc-missing"), delete_after=DELETE_RESPONSE_TIME)
            return

        try:
            await self.bot.client.edit_message_text(chat_id, room_info["description_id"], await self.text(chat_id, "rooms-description", room_desc=desc, username=ctx.author.username)) # No description --> create new
        except:
            description: Message = await self.bot.client.send_message(chat_id, await self.text(chat_id, "rooms-description", room_desc=desc, username=ctx.author.username), message_thread_id=ctx.msg.message_thread_id)
            await description.pin()
            await self.db.update_one(
                {"chat_id": chat_id},
                {
                    "$set": {
                        f"topics.{ctx.msg.message_thread_id}.description_id": description.id
                    }
                }
            )
            self.rooms[chat_id][ctx.msg.message_thread_id]["description_id"] = description.id

    @command.filters(filters.can_manage_topic)
    async def cmd_deleteroom(self, ctx: command.Context) -> Optional[str]:
        """Delete room including data in db"""
        if not ctx.chat.is_forum:
            await ctx.respond(await self.text(ctx.chat.id, "rooms-non-topic"), delete_after=DELETE_RESPONSE_TIME)
            return

        await ctx.respond(
            await self.text(ctx.chat.id, "rooms-remove-confirm"),
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            text= await self.text(ctx.chat.id, "rooms-delete-button"),
                            callback_data="rooms_action_remove",
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            text= await self.text(ctx.chat.id, "rooms-cancel-button"),
                            callback_data="rooms_action_cancel",
                        )
                    ],
                ]
            ),
        )

    @listener.filters(filters.regex(r"rooms_action_(.*)"))
    async def on_callback_query(self, query: CallbackQuery) -> None:
        action = query.matches[0].group(1)
        chat = query.message.chat
        thread_id = query.message.message_thread_id

        user = await chat.get_member(query.from_user.id)
        if not user.privileges or not user.privileges.can_manage_topics:
            await query.answer(await self.text(chat.id, "error-no-rights"))
            return

        room_info: RoomInfo = await self.get_room_info(chat.id, thread_id)
        if not room_info:
            await query.message.delete()
            await ctx.respond(await self.text(ctx.chat.id, "rooms-non-room"), delete_after=DELETE_RESPONSE_TIME)
            return

        if action == "cancel":
            await query.message.delete()
            return
        if action == "remove":
            asyncio.gather(
                self.bot.client.delete_forum_topic(chat.id, thread_id),
                self.db.update_one(
                    {"chat_id": chat.id},
                    {"$unset": {f"topics.{str(thread_id)}": ""}}
                )
            )

        room_info = None
