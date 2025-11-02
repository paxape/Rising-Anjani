"""Plugin to lock joining groups"""
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

import sys
from typing import ClassVar

if sys.version_info >= (3, 10):
    from aiopath import AsyncPurePosixPath as PosixPath
else:
    from aiopath import PureAsyncPosixPath as PosixPath

from pyrogram.types import Message

from anjani import listener, plugin


class LockJoining(plugin.Plugin):
    name: ClassVar[str] = "LockJoining"
    disabled: ClassVar[bool] = False
    helpable: ClassVar[bool] = False

    @listener.priority(150)
    async def on_chat_action(self, message: Message) -> None:
        if message.new_chat_members:
            for new_member in message.new_chat_members:
                if new_member.is_self: # Bot will leave all chats when it's added. (deactivate plugin in order to add it to a chat)
                        await self.bot.client.leave_chat(message.chat.id)
