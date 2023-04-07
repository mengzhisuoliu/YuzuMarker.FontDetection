import argparse
import os
import gradio as gr
from PIL import Image
from torchvision import transforms
from detector.model import *
from detector import config
from font_dataset.font import load_fonts, load_font_with_exclusion

parser = argparse.ArgumentParser()
parser.add_argument(
    "-d",
    "--device",
    type=int,
    default=0,
    help="GPU devices to use (default: 0), -1 for CPU",
)
parser.add_argument(
    "-c",
    "--checkpoint",
    type=str,
    default=None,
    help="Trainer checkpoint path (default: None)",
)
parser.add_argument(
    "-m",
    "--model",
    type=str,
    default="resnet18",
    choices=["resnet18", "resnet34", "resnet50", "resnet101", "deepfont"],
    help="Model to use (default: resnet18)",
)
parser.add_argument(
    "-f",
    "--font-classification-only",
    action="store_true",
    help="Font classification only (default: False)",
)
parser.add_argument(
    "-z",
    "--size",
    type=int,
    default=512,
    help="Model feature image input size (default: 512)",
)
parser.add_argument(
    "-s",
    "--share",
    action="store_true",
    help="Get public link via Gradio (default: False)",
)

args = parser.parse_args()

config.INPUT_SIZE = args.size
device = torch.device("cpu") if args.device == -1 else torch.device("cuda", args.device)

regression_use_tanh = False

if args.model == "resnet18":
    model = ResNet18Regressor(regression_use_tanh=regression_use_tanh)
elif args.model == "resnet34":
    model = ResNet34Regressor(regression_use_tanh=regression_use_tanh)
elif args.model == "resnet50":
    model = ResNet50Regressor(regression_use_tanh=regression_use_tanh)
elif args.model == "resnet101":
    model = ResNet101Regressor(regression_use_tanh=regression_use_tanh)
elif args.model == "deepfont":
    assert args.pretrained is False
    assert args.size == 105
    assert args.font_classification_only is True
    model = DeepFontBaseline()
else:
    raise NotImplementedError()

if torch.__version__ >= "2.0" and os.name == "posix":
    model = torch.compile(model)

detector = FontDetector(
    model=model,
    lambda_font=1,
    lambda_direction=1,
    lambda_regression=1,
    font_classification_only=args.font_classification_only,
    lr=1,
    betas=(1, 1),
    num_warmup_iters=1,
    num_iters=1e9,
    num_epochs=1e9,
)
detector.load_from_checkpoint(
    args.checkpoint,
    map_location=device,
    model=model,
    lambda_font=1,
    lambda_direction=1,
    lambda_regression=1,
    font_classification_only=args.font_classification_only,
    lr=1,
    betas=(1, 1),
    num_warmup_iters=1,
    num_iters=1e9,
    num_epochs=1e9,
)
detector = detector.to(device)
detector.eval()


transform = transforms.Compose(
    [
        transforms.Resize((512, 512)),
        transforms.ToTensor(),
    ]
)

print("Preparing fonts ...")
font_list, exclusion_rule = load_fonts()

font_list = list(filter(lambda x: not exclusion_rule(x), font_list))
font_list.sort(key=lambda x: x.path)

for i in range(len(font_list)):
    font_list[i].path = font_list[i].path[18:]  # remove ./dataset/fonts/./ prefix

font_demo_images = []

for i in range(len(font_list)):
    font_demo_images.append(Image.open(f"demo_fonts/{i}.jpg").convert("RGB"))


def recognize_font(image):
    transformed_image = transform(image)
    with torch.no_grad():
        transformed_image = transformed_image.to(device)
        output = detector(transformed_image.unsqueeze(0))
        prob = output[0][: config.FONT_COUNT].softmax(dim=0)

        indicies = torch.topk(prob, 9)[1]

        return [
            {font_list[i].path: float(prob[i]) for i in range(config.FONT_COUNT)},
            *[gr.Image.update(value=font_demo_images[indicies[i]]) for i in range(9)],
            *[
                gr.Markdown.update(
                    value=f"**Font Name**: {font_list[indicies[i]].path}"
                )
                for i in range(9)
            ],
        ]


def generate_grid(num_columns, num_rows):
    ret_images, ret_labels = [], []
    with gr.Column():
        for _ in range(num_rows):
            with gr.Row():
                for _ in range(num_columns):
                    with gr.Column():
                        ret_labels.append(gr.Markdown("**Font Name**"))
                        ret_images.append(gr.Image())
    return ret_images, ret_labels


with gr.Blocks() as demo:
    with gr.Column():
        with gr.Row():
            inp = gr.Image(type="pil", label="Input Image")
            out = gr.Label(num_top_classes=9, label="Output Font")
        font_demo_images_blocks, font_demo_labels_blocks = generate_grid(3, 3)

    submit_button = gr.Button(label="Submit")
    submit_button.click(
        fn=recognize_font,
        inputs=inp,
        outputs=[out, *font_demo_images_blocks, *font_demo_labels_blocks],
    )


demo.launch(share=args.share)
