import board
import busio
import adafruit_ssd1306
from PIL import Image, ImageDraw, ImageFont

# Import the base Node class from your architecture
from Node import Node

class SSD1306Node(Node):
    def __init__(self, name="SSD1306_OLED", width=128, height=64, i2c_address=0x3C):
        """
        Initializes the SSD1306 OLED Display Node.
        """
        super().__init__(name)
        self.width = width
        self.height = height
        
        try:
            # Initialize I2C bus
            self.i2c = busio.I2C(board.SCL, board.SDA)
            
            # Initialize the SSD1306 display
            self.display = adafruit_ssd1306.SSD1306_I2C(
                self.width, 
                self.height, 
                self.i2c, 
                addr=i2c_address
            )
            
            # Clear display on startup
            self.display.fill(0)
            self.display.show()
            self.is_connected = True
            
        except Exception as e:
            print(f"[{self.name}] Failed to initialize I2C/SSD1306: {e}")
            self.is_connected = False

        # Create a blank image for drawing (1-bit color for OLEDs)
        self.image = Image.new("1", (self.width, self.height))
        self.draw = ImageDraw.Draw(self.image)
        
        # Load a default font (fallback to built-in if truetype fails)
        try:
            self.font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 12)
        except IOError:
            self.font = ImageFont.load_default()

    def process(self, payload):
        """
        Processes the incoming payload and updates the OLED screen.
        """
        if not self.is_connected:
            return payload

        # 1. Clear the image canvas
        self.draw.rectangle((0, 0, self.width, self.height), outline=0, fill=0)
        
        # 2. Extract data from the Schema payload
        # (Adjust 'detections' and 'label' based on your exact Schema.py definitions)
        detections = getattr(payload, 'detections', [])
        num_detections = len(detections)
        
        # 3. Draw information to the canvas
        self.draw.text((0, 0), "EyeAria Pipeline", font=self.font, fill=255)
        self.draw.line((0, 14, self.width, 14), fill=255)
        
        self.draw.text((0, 18), f"Objects Found: {num_detections}", font=self.font, fill=255)
        
        if num_detections > 0:
            # Display the label and confidence of the first detected object
            first_det = detections[0]
            label = getattr(first_det, 'label', 'Unknown')
            conf = getattr(first_det, 'confidence', 0.0)
            
            self.draw.text((0, 34), f"1: {label}", font=self.font, fill=255)
            self.draw.text((0, 48), f"Conf: {conf:.2f}", font=self.font, fill=255)

        # 4. Push the image to the OLED
        self.display.image(self.image)
        self.display.show()
        
        # 5. Return payload for the next node in the pipeline
        return payload