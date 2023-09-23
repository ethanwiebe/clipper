require 'mp'
require 'mp.msg'

-- Copy the current time of the video to clipboard.

WINDOWS = 2
UNIX = 3

local function platform_type()
    local utils = require 'mp.utils'
    local workdir = utils.to_string(mp.get_property_native("working-directory"))
    if string.find(workdir, "\\") then
        return WINDOWS
    else
        return UNIX
    end
end

local function command_exists(cmd)
    local pipe = io.popen("type " .. cmd .. " > /dev/null 2> /dev/null; printf \"$?\"", "r")
    exists = pipe:read() == "0"
    pipe:close()
    return exists
end

local function get_clipboard_cmd()
    if command_exists("xclip") then
        return "xclip -silent -in -selection clipboard"
    elseif command_exists("wl-copy") then
        return "wl-copy"
    elseif command_exists("pbcopy") then
        return "pbcopy"
    else
        mp.msg.error("No supported clipboard command found")
        return false
    end
end

local function divmod(a, b)
    return math.floor(a / b), a % b
end

local function set_clipboard(text) 
    if platform == WINDOWS then
        mp.commandv("run", "powershell", "set-clipboard", string.format('"%s"',text))
        return true
    elseif (platform == UNIX and clipboard_cmd) then
        local pipe = io.popen(clipboard_cmd, "w")
        pipe:write(text)
        pipe:close()
        return true
    else
        mp.msg.error("Set_clipboard error")
        return false
    end
end

local function get_clipboard()
	if platform == WINDOWS then
		local res = mp.command_native({
			name = "subprocess",
			playback_only = true,
			capture_stdout = true,
			args = {"powershell", "get-clipboard"},
		})
		
		if res.status == 0 then
			local r = res.stdout
			r = r:sub(1,-3)
			return r
		else
			return nil
		end
    else
        mp.msg.error("Get_clipboard error")
        return nil
    end
end

local function copyTime()
    local time_pos = mp.get_property_number("time-pos")
    local minutes, remainder = divmod(time_pos, 60)
    local hours, minutes = divmod(minutes, 60)
    local seconds = math.floor(remainder)
    local milliseconds = math.floor((remainder % 1.0) * 1000+0.5)
    local time = string.format("%02d:%02d:%02d.%03d", hours, minutes, seconds, milliseconds)
    if set_clipboard(time) then
        mp.osd_message(string.format("Copied to clipboard: %s", time))
    else
        mp.osd_message("Failed to copy time to clipboard")
    end
end

local function copyCoords()
	local x,y = mp.get_mouse_pos()
	local w,h = mp.get_property_number('width'),mp.get_property_number('height')
	local rx,ry = mp.get_property_number('osd-width'),mp.get_property_number('osd-height')
	local pos = string.format("%d %d",math.floor(x*w/rx),math.floor(y*h/ry))
	if set_clipboard(pos) then
        mp.osd_message(string.format("Copied position: %s",pos))
    else
        mp.osd_message("Failed to copy position to clipboard")
    end
end

function string:split(delimiter)
	local result = {}
	local from = 1
	local delim_from, delim_to = string.find(self, delimiter, from)
	while delim_from do
		table.insert(result, string.sub(self, from, delim_from-1))
		from = delim_to + 1
		delim_from, delim_to = string.find(self, delimiter, from)
	end
	table.insert(result, string.sub(self, from))
	return result
end

local function pasteTime()
	local clipText = get_clipboard()
	
	if clipText == nil then
		mp.osd_message("Bad time")
		return
	end
	
	local splitted = clipText:split(":")
	local count = table.getn(splitted)
	if count > 3 or count < 1 then
		mp.osd_message("Bad time")
		return
	end
	
	local t = 0.0
	
	if count==3 then
		local hours = tonumber(splitted[1])
		local minutes = tonumber(splitted[2])
		local seconds = tonumber(splitted[3])
		
		t = seconds+minutes*60+hours*60*60
	elseif count==2 then
		local minutes = tonumber(splitted[1])
		local seconds = tonumber(splitted[2])
		
		t = seconds+minutes*60
	elseif count==1 then
		t = tonumber(splitted[1])
	end
	
	mp.osd_message(string.format("Seeking to: %s",clipText))
    
	mp.set_property_number("time-pos",t)
end

platform = platform_type()
if platform == UNIX then
    clipboard_cmd = get_clipboard_cmd()
end

mp.add_key_binding("Ctrl+c", "copyTime", copyTime)
mp.add_key_binding("Ctrl+v", "pasteTime", pasteTime)
mp.add_key_binding("Ctrl+x", "copyCoords", copyCoords)