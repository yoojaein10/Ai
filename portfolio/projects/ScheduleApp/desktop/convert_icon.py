from PIL import Image
import os

def convert_to_ico(input_path, output_path):
    img = Image.open(input_path)
    # Define standard Windows icon sizes
    icon_sizes = [(16, 16), (32, 32), (48, 48), (256, 256)]
    img.save(output_path, format='ICO', sizes=icon_sizes)
    print(f"Successfully converted {input_path} to {output_path} with sizes {icon_sizes}")

if __name__ == "__main__":
    current_dir = os.path.dirname(os.path.abspath(__file__))
    input_file = os.path.join(current_dir, "assets", "Cal.png")
    output_file = os.path.join(current_dir, "assets", "Cal.ico")
    
    if os.path.exists(input_file):
        convert_to_ico(input_file, output_file)
    else:
        print(f"Error: Could not find input file at {input_file}")
