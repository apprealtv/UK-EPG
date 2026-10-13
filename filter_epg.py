import xml.etree.ElementTree as ET

KEEP_CHANNELS = {
    # ITV
    'ITV1.HD.uk',
    'ITV2.HD.uk',
    'ITV3.HD.uk',
    'ITV4.HD.uk',

    # Sky Sports
    'SkySp.ActionHD.uk',
    'SkySpCricket.HD.uk',
    'SkySp.F1.HD.uk',
    'SkySp.Fball.HD.uk',
    'SkySp.Golf.HD.uk',
    'SkySpMainEvHD.uk',
    'SkySp.Mix.HD.uk',
    'SkySp.News.HD.uk',
    'SkySp.PL.HD.uk',
    'SkySp.Racing.HD.uk',
    'SkySp.Tennis.HD.uk',
    'SkySp+.uk',

    # TNT / BT Sports
    'TNT.Sports.1.HD.uk',
    'TNT.Sports.2.HD.uk',
    'TNT.Sports.3.HD.uk',
    'TNT.Sports.4.HD.uk',
}

INPUT_FILE = 'epg_ripper_UK1.xml'

tree = ET.parse(INPUT_FILE)
root = tree.getroot()

kept_channels = 0
kept_programmes = 0

for elem in list(root):
    if elem.tag == 'channel':
        if elem.get('id') in KEEP_CHANNELS:
            kept_channels += 1
        else:
            root.remove(elem)
    elif elem.tag == 'programme':
        if elem.get('channel') in KEEP_CHANNELS:
            kept_programmes += 1
        else:
            root.remove(elem)

tree.write(INPUT_FILE, encoding='UTF-8', xml_declaration=True)

print(f'Kept {kept_channels} channels and {kept_programmes} programmes')
