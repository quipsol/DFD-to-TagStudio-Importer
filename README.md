# DFD to TagStudio Importer

This tool is designed to import tags from a database created by the [Danbooru Favourites Downloader](https://github.com/quipsol/Danbooru-Favourites-Downloader) into a [TagStudio](https://docs.tagstud.io) library. **This tool does not move the files themselves but only imports associated tags**.

## Download

Download the project files and install the required dependencies

1. Download files
2. Install python from [Python.org](https://www.python.org)
3. run this command from the projects directory to install dependencies

       py -m pip install -r requirements.txt

## Setup

1. Create a ".env" file in the directory
2. Add the following keys and values to your .env file

    - DFD_DATABASE_LOCATION = Path to the location of the database created by the [Danbooru Favourites Downloader](https://github.com/quipsol/Danbooru-Favourites-Downloader) (post-downloads.db)
    - TAG_STUDIO_DATABASE_LOCATION = Path to the location of your TagStudio library database (ts_library.sqlite)
    - ARTIST_COLOR = The color for artist tags
    - COPYRIGHT_COLOR = The color for copyright tags
    - CHARACTER_COLOR = The color for character tags
    - GENERAL_COLOR = The color for general tags 
    - META_COLOR = The color for meta tags
   
All COLOR tags are optional and have default values set to closely match the respective colors on Danbooru. You can find all available colors either in the TagStudio software or on their website here: <https://docs.tagstud.io/colors/#tag-color-manager>

The color "TagStudio Grayscale -> Dark Gray" would be written as "tagstudio-grayscale,dark-gray" in the .env file.

Example .env file:

    DFD_DATABASE_LOCATION=C:/Danbooru-Favourites-Downloader/post-downloads.db
    TAG_STUDIO_DATABASE_LOCATION=C:/TagStudio Library/.TagStudio/ts_library.sqlite

with optional parameters:

    ARTIST_COLOR=tagstudio-standard,red-orange
    COPYRIGHT_COLOR=tagstudio-standard,indigo
    CHARACTER_COLOR=tagstudio-standard,green
    GENERAL_COLOR=tagstudio-standard,blue
    META_COLOR=tagstudio-standard,yellow

## Running the program

Make sure that all files are in the TagStudio library folder.

Important: The file names that the *Danbooru Favourites Downloader* creates must be left unchanged!

Run any of the relevant python files

- **import_tags**: Import and assign all tags to TagStudio
- **import_tags_with_implications**: Additionally, check if there are any implication relations between any of the tags and if so, add those too.

### Note about implications

An Implication would be the tag ***absurdres*** implying the tag ***highres***. Any file with the tag ***absurdres*** would therefore automatically have the tag ***highres*** too.

*import_tags_with_implications* would check for such relations and import them into the TagStudio library.

This has no effect on how the tags are displayed in TagStudio! It merely adds the implication relation to the TagStudio library, so that in the future, if you tag a file inside of TagStudio with ***absurdres***, TagStudio will automatically also add the tag ***highres*** to that file. (Or any other relation between tags)

Due to limitations on how fast data can be polled from Danbooru, this process has an immense increase on runtime, especially during the first time execution.

***

For a smooth experience it is recommended to do the following

1. Set the *Danbooru Favourites Downloader* file save location to the folder of the TagStudio library.
2. After downloading new files from Danbooru, start TagStudio and refresh the library (**CTRL/CMD+R** or click on **Files -> Refresh Directories**).
3. Run this tool.

<br>

*Example of imported tags in TagStudio*

![alternative text](Local/tag_on_image_full_example.png)
